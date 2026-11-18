import { cutAt } from './geometry';
import { useEditor } from './store';

/** Imperative handle for the editor's main <video>; shared by preview, timeline, panels and shortcuts. */
class Player {
  video: HTMLVideoElement | null = null;
  followers = new Set<HTMLVideoElement>();
  private raf = 0;

  attach(v: HTMLVideoElement | null) {
    this.video = v;
  }

  seek(t: number) {
    const st = useEditor.getState();
    const dur = st.data?.media?.duration ?? Infinity;
    const tt = Math.max(0, Math.min(dur, t));
    if (this.video) this.video.currentTime = tt;
    for (const f of this.followers) f.currentTime = tt;
    st.set({ time: tt });
  }

  play() {
    const v = this.video;
    const st = useEditor.getState();
    if (!v || !st.timeline) return;
    const tl = st.timeline;
    if (v.currentTime >= tl.end - 0.05 || v.currentTime < tl.start - 0.5) this.seek(tl.start);
    void v.play().catch(() => undefined);
  }

  pause() {
    this.video?.pause();
  }

  toggle() {
    if (!this.video) return;
    if (this.video.paused) this.play();
    else this.pause();
  }

  step(dt: number) {
    this.pause();
    const t = this.video ? this.video.currentTime : useEditor.getState().time;
    this.seek(t + dt);
  }

  /** Called every animation frame while playing: enforces cuts, clip end and loop; syncs followers. */
  tick = () => {
    const v = this.video;
    const st = useEditor.getState();
    if (!v || !st.timeline) return;
    const tl = st.timeline;
    let t = v.currentTime;
    if (!v.paused) {
      const c = cutAt(tl.cuts, t);
      if (c) {
        v.currentTime = c.e;
        t = c.e;
      }
      if (t >= tl.end) {
        if (st.loop) {
          v.currentTime = tl.start;
          t = tl.start;
        } else {
          v.pause();
          v.currentTime = tl.end;
          t = tl.end;
        }
      }
    }
    for (const f of this.followers) {
      if (Math.abs(f.currentTime - t) > 0.12) f.currentTime = t;
      if (v.paused && !f.paused) f.pause();
      if (!v.paused && f.paused) void f.play().catch(() => undefined);
    }
    if (Math.abs(st.time - t) > 0.0005) st.set({ time: t });
  };

  startLoop() {
    cancelAnimationFrame(this.raf);
    const loop = () => {
      this.tick();
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stopLoop() {
    cancelAnimationFrame(this.raf);
  }
}

export const player = new Player();
