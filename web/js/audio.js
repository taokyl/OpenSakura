// audio.js — voice playback with an analyser (for lipsync) and a VAD / push-to-talk microphone.

export class Player {
  constructor() {
    this.ctx = null;
    this.analyser = null;
    this._buf = null;
    this._source = null;
    this._queue = [];
    this._playing = false;
    this.onStart = () => {};
    this.onEnd = () => {};
  }

  get playing() { return this._playing; }

  async unlock() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      this.analyser.smoothingTimeConstant = 0.4;
      this.analyser.connect(this.ctx.destination);
      this._buf = new Float32Array(this.analyser.fftSize);
    }
    if (this.ctx.state !== 'running') await this.ctx.resume();
    return this.ctx.state === 'running';
  }

  level() {
    if (!this.analyser || !this._playing) return 0;
    this.analyser.getFloatTimeDomainData(this._buf);
    let s = 0;
    for (let i = 0; i < this._buf.length; i++) s += this._buf[i] * this._buf[i];
    const rms = Math.sqrt(s / this._buf.length);
    // speech RMS sits around 0.05–0.2; map that to 0..1 with a soft knee so loud peaks don't pin the jaw
    return Math.min(1, Math.pow(Math.min(1, rms * 4.5), 0.85));
  }

  /** Queue a base64 audio blob (wav/ogg); resolves when THIS clip finished (or was stopped). */
  play(b64, { format = 'wav', meta = {} } = {}) {
    return new Promise((resolve) => {
      this._queue.push({ b64, format, meta, resolve });
      this._drain();
    });
  }

  async _drain() {
    if (this._playing || !this._queue.length) return;
    const item = this._queue.shift();
    this._playing = true;
    try {
      await this.unlock();
      const bin = atob(item.b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const audio = await this.ctx.decodeAudioData(bytes.buffer.slice(0));
      const src = this.ctx.createBufferSource();
      src.buffer = audio;
      src.connect(this.analyser);
      this._source = src;
      this.onStart(item.meta, audio.duration);
      await new Promise((done) => { src.onended = done; src.start(); });
    } catch (e) {
      console.warn('audio play failed', e);
      item.meta.error = String(e);
    } finally {
      this._source = null;
      this._playing = false;
      this.onEnd(item.meta);
      item.resolve(item.meta);
      this._drain();
    }
  }

  stop() {
    this._queue.splice(0).forEach((i) => i.resolve({ ...i.meta, stopped: true }));
    if (this._source) { try { this._source.stop(); } catch (e) { /* already stopped */ } }
  }
}

function floatTo16kWav(chunks, srcRate) {
  const total = chunks.reduce((a, c) => a + c.length, 0);
  const data = new Float32Array(total);
  let o = 0; for (const c of chunks) { data.set(c, o); o += c.length; }
  const ratio = srcRate / 16000;
  const n = Math.floor(data.length / ratio);
  const pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const pos = i * ratio, i0 = Math.floor(pos), i1 = Math.min(data.length - 1, i0 + 1), f = pos - i0;
    const v = data[i0] * (1 - f) + data[i1] * f;
    pcm[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
  }
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const dv = new DataView(buf);
  const str = (off, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, 16000, true);
  dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); str(36, 'data');
  dv.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: 'audio/wav' });
}

/**
 * Microphone with two modes:
 *   vad  — auto segments speech by energy (start/stop thresholds + hangover)
 *   ptt  — record between pttStart() and pttStop()
 * onUtterance(blob, seconds) fires with a 16 kHz mono WAV.
 */
export class Mic {
  constructor({ onUtterance, onLevel, onSpeechStart, onState } = {}) {
    this.onUtterance = onUtterance || (() => {});
    this.onLevel = onLevel || (() => {});
    this.onSpeechStart = onSpeechStart || (() => {});
    this.onState = onState || (() => {});
    this.mode = 'vad';
    this.ctx = null; this.stream = null; this.proc = null;
    this._chunks = []; this._pre = []; this._speaking = false; this._silenceMs = 0; this._speechMs = 0;
    this._noise = 0.01; this._ptt = false; this.active = false;
    this.cfg = { startMul: 3.0, minStart: 0.012, stopMul: 1.6, hangoverMs: 800, minSpeechMs: 350, maxMs: 15000, preRollMs: 300 };
  }

  async start(mode = 'vad') {
    this.mode = mode;
    if (this.active) return;
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.proc = this.ctx.createScriptProcessor(2048, 1, 1);
    src.connect(this.proc); this.proc.connect(this.ctx.destination);
    this.proc.onaudioprocess = (e) => this._onAudio(e.inputBuffer.getChannelData(0));
    this.active = true;
    this.onState({ active: true, mode });
  }

  stop() {
    if (!this.active) return;
    try { this.proc.disconnect(); } catch (e) { /* noop */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.active = false; this._speaking = false; this._chunks = []; this._pre = []; this._ptt = false;
    this.onState({ active: false, mode: this.mode });
    this.onLevel(0);
  }

  pttStart() { if (!this.active) return; this._ptt = true; this._chunks = []; this._speechMs = 0; this.onSpeechStart(); }
  pttStop() {
    if (!this.active || !this._ptt) return;
    this._ptt = false;
    const secs = this._speechMs / 1000;
    const chunks = this._chunks; this._chunks = [];
    if (secs >= 0.25) this.onUtterance(floatTo16kWav(chunks, this.ctx.sampleRate), secs);
  }

  _onAudio(f32) {
    const frame = new Float32Array(f32);
    let s = 0; for (let i = 0; i < frame.length; i++) s += frame[i] * frame[i];
    const rms = Math.sqrt(s / frame.length);
    const ms = (frame.length / this.ctx.sampleRate) * 1000;
    this.onLevel(Math.min(1, rms * 8));
    if (this.mode === 'ptt') {
      if (this._ptt) { this._chunks.push(frame); this._speechMs += ms; }
      return;
    }
    // adaptive noise floor (only tracks when not speaking)
    if (!this._speaking) this._noise = this._noise * 0.97 + rms * 0.03;
    const startThr = Math.max(this.cfg.minStart, this._noise * this.cfg.startMul);
    const stopThr = Math.max(this.cfg.minStart * 0.6, this._noise * this.cfg.stopMul);
    if (!this._speaking) {
      this._pre.push(frame);
      const preMax = Math.ceil(this.cfg.preRollMs / ms);
      while (this._pre.length > preMax) this._pre.shift();
      if (rms > startThr) {
        this._speaking = true; this._silenceMs = 0; this._speechMs = 0;
        this._chunks = this._pre.slice(); this._pre = [];
        this.onSpeechStart();
      }
      return;
    }
    this._chunks.push(frame); this._speechMs += ms;
    if (rms < stopThr) this._silenceMs += ms; else this._silenceMs = 0;
    if (this._silenceMs >= this.cfg.hangoverMs || this._speechMs >= this.cfg.maxMs) {
      this._speaking = false;
      const voiced = this._speechMs - this._silenceMs;
      const chunks = this._chunks; this._chunks = [];
      if (voiced >= this.cfg.minSpeechMs) this.onUtterance(floatTo16kWav(chunks, this.ctx.sampleRate), this._speechMs / 1000);
    }
  }
}
