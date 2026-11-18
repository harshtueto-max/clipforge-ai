import { ChevronsLeftRight, Languages, Loader2, Merge, RotateCcw, Scissors, Trash2, Wand2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api, errMsg } from '../api';
import { Button, Field, IconButton, Select, Slider, Toggle } from '../components/ui';
import { cx, fmtTime, uid } from '../lib/format';
import { useFetch } from '../lib/hooks';
import { toast } from '../stores/toast';
import type { CaptionAnimation, CaptionItem, CaptionPosition, CaptionStyle } from '../types';
import { round3 } from './geometry';
import { Section } from './panels';
import { player } from './player';
import { useEditor } from './store';

const CAPTION_LANG_MODES: { mode: 'hinglish' | 'hi' | 'en'; title: string; sub: string; langAttr?: string }[] = [
  { mode: 'hinglish', title: 'Hinglish', sub: 'Roman Hindi + EN' },
  { mode: 'hi', title: 'हिन्दी (Hindi)', sub: 'Devanagari script', langAttr: 'hi' },
  { mode: 'en', title: 'English', sub: 'English / translate' },
];

const POSITIONS: { value: CaptionPosition; label: string }[] = [
  { value: 'top', label: 'Top' },
  { value: 'center', label: 'Center' },
  { value: 'center_low', label: 'Center low' },
  { value: 'bottom', label: 'Bottom' },
];
const ANIMS: { value: CaptionAnimation; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'fade', label: 'Fade' },
  { value: 'pop', label: 'Pop' },
  { value: 'highlight', label: 'Word highlight' },
  { value: 'karaoke', label: 'Karaoke' },
];

function Color({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 text-2xs text-ink-200">
      {label}
      <input type="color" value={value || '#ffffff'} onChange={(e) => onChange(e.target.value.toUpperCase())} />
    </label>
  );
}

export function CaptionsPanel() {
  const data = useEditor((s) => s.data);
  const captions = useEditor((s) => s.captions);
  const selCaption = useEditor((s) => s.selCaption);
  const time = useEditor((s) => s.time);
  const commit = useEditor((s) => s.commit);
  const flush = useEditor((s) => s.flush);
  const applyServerCaptions = useEditor((s) => s.applyServerCaptions);
  const setStore = useEditor((s) => s.set);
  const fonts = useFetch(() => api.fonts(), []);
  const [wpc, setWpc] = useState(captions?.style.words_per_caption ?? 4);
  const [busy, setBusy] = useState(false);
  const [genLang, setGenLang] = useState<null | 'hinglish' | 'hi' | 'en'>(null);
  const [activeLang, setActiveLang] = useState<null | 'hinglish' | 'hi' | 'en'>(null);
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setWpc(captions?.style.words_per_caption ?? 4);
    setActiveLang(null);
  }, [data?.clip.id]);
  useEffect(() => setWpc(captions?.style.words_per_caption ?? 4), [captions?.style.words_per_caption]);
  useEffect(() => {
    if (!selCaption || !listRef.current) return;
    listRef.current.querySelector(`[data-cap="${selCaption}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [selCaption]);
  if (!data || !captions) return null;
  const st = captions.style;
  const styles = data.caption_styles;
  const detectedDevanagari = captions.items.some((it) => /[\u0900-\u097F]/.test(it.text));
  const currentLang = activeLang ?? (detectedDevanagari ? 'hi' : null);
  const setStyle = <K extends keyof CaptionStyle>(k: K, v: CaptionStyle[K], merge = true) =>
    commit((s) => {
      s.captions.style = { ...s.captions.style, [k]: v };
      return s;
    }, merge ? `style-${String(k)}` : undefined);
  const pickStyle = (id: string) =>
    commit((s) => {
      s.captions.style = { ...styles[id], id };
      return s;
    });
  const updItem = (id: string, fn: (it: CaptionItem) => void, key?: string) =>
    commit((s) => {
      const it = s.captions.items.find((x) => x.id === id);
      if (it) fn(it);
      return s;
    }, key);
  const rebuild = async () => {
    setBusy(true);
    try {
      await flush();
      const r = await api.rebuildCaptions(data.clip.id, { words_per_caption: wpc });
      applyServerCaptions({ style: r.style, items: r.items });
      setActiveLang(null);
      toast.success(`Rebuilt ${r.items.length} captions from the transcript`);
    } catch (e) {
      toast.error('Rebuild failed', errMsg(e));
    } finally {
      setBusy(false);
    }
  };
  const switchLanguage = async (mode: 'hinglish' | 'hi' | 'en', label: string) => {
    setGenLang(mode);
    try {
      await flush();
      const r = await api.captionLanguage(data.clip.id, { mode, words_per_caption: wpc });
      applyServerCaptions({ style: r.style, items: r.items });
      setActiveLang(mode);
      toast.success(`Generated ${r.items.length} ${label} captions (${r.model})`);
    } catch (e) {
      toast.error(`Could not generate ${label} captions`, errMsg(e));
    } finally {
      setGenLang(null);
    }
  };
  const merge = (idx: number) =>
    commit((s) => {
      const a = s.captions.items[idx];
      const b = s.captions.items[idx + 1];
      if (!a || !b) return s;
      a.text = `${a.text} ${b.text}`;
      a.end = b.end;
      a.words = [...(a.words ?? []), ...(b.words ?? [])];
      s.captions.items.splice(idx + 1, 1);
      return s;
    });
  const split = (idx: number) => {
    const cur = captions.items[idx];
    if (!cur || cur.end - cur.start < 0.25) {
      toast.info('Caption is too short to split');
      return;
    }
    commit((s) => {
      const a = s.captions.items[idx];
      if (!a || a.end - a.start < 0.25) return s;
      const toks = a.text.replace(/\n/g, ' ').split(' ').filter(Boolean);
      if (toks.length < 2) return s;
      const ws = a.words ?? [];
      let k = Math.ceil(toks.length / 2);
      // prefer splitting at the playhead word when it falls inside this caption
      if (ws.length === toks.length && time > a.start && time < a.end) {
        const j = ws.findIndex((w) => w.s >= time);
        if (j > 0) k = j;
      }
      const rawCut = ws.length === toks.length ? ws[k].s : a.start + ((a.end - a.start) * k) / toks.length;
      const cut = round3(Math.max(a.start + 0.12, Math.min(a.end - 0.12, rawCut)));
      const b: CaptionItem = { id: uid(), start: cut, end: round3(Math.max(cut + 0.12, a.end)), text: toks.slice(k).join(' '), words: ws.length === toks.length ? ws.slice(k) : [], style: { ...a.style } };
      a.text = toks.slice(0, k).join(' ');
      a.end = cut;
      a.words = ws.length === toks.length ? ws.slice(0, k) : [];
      s.captions.items.splice(idx + 1, 0, b);
      return s;
    });
  };

  return (
    <div>
      <Section title="Caption language">
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-3 gap-1.5">
            {CAPTION_LANG_MODES.map((m) => {
              const isSel = currentLang === m.mode;
              const isLoading = genLang === m.mode;
              return (
                <button
                  key={m.mode}
                  type="button"
                  disabled={genLang !== null || busy}
                  aria-pressed={isSel}
                  onClick={() => switchLanguage(m.mode, m.mode === 'hi' ? 'Hindi' : m.title)}
                  className={cx(
                    'flex min-h-11 flex-col items-center justify-center rounded-md border px-2 py-1.5 text-center transition-colors disabled:opacity-60',
                    isSel ? 'border-amber-500/80 bg-amber-500/10 text-ink-50' : 'border-ink-600 bg-ink-850 text-ink-100 hover:border-ink-400',
                  )}
                >
                  <span className="flex items-center gap-1 text-xs font-semibold leading-snug">
                    {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-400" aria-hidden="true" /> : <Languages className="h-3 w-3 text-amber-400/90" aria-hidden="true" />}
                    {m.mode === 'hi' ? (
                      <span>
                        <span lang="hi">हिन्दी</span> (Hindi)
                      </span>
                    ) : (
                      <span>{m.title}</span>
                    )}
                  </span>
                  <span className="mt-0.5 text-[10px] leading-tight text-ink-300">{isLoading ? 'Generating…' : m.sub}</span>
                </button>
              );
            })}
          </div>
          <p className="text-[11px] leading-relaxed text-ink-300">
            Re-transcribes or translates this clip locally from the cached audio — <b className="text-ink-100">Hinglish</b> keeps Hindi + English in Roman script, <b className="text-ink-100" lang="hi">हिन्दी</b> uses Devanagari with Nirmala UI, and <b className="text-ink-100">English</b> translates Hindi speech offline.
          </p>
        </div>
      </Section>
      <Section title="Caption style">
        <div className="grid grid-cols-2 gap-1.5">
          {Object.entries(styles).map(([id, sty]) => (
            <button
              key={id}
              onClick={() => pickStyle(id)}
              className={cx('flex min-h-14 flex-col items-center justify-center rounded-md border bg-gradient-to-b from-ink-700 to-ink-900 px-1 py-1.5 transition-colors', st.id === id ? 'border-amber-500/80' : 'border-ink-600 hover:border-ink-400')}
            >
              <span
                style={{
                  fontFamily: `"${sty.font}", "Nirmala UI", sans-serif`,
                  fontWeight: sty.bold ? 800 : 500,
                  color: sty.color,
                  textTransform: sty.uppercase ? 'uppercase' : undefined,
                  textShadow: sty.stroke ? `0 0 2px ${sty.stroke_color}, 0 0 2px ${sty.stroke_color}` : undefined,
                  background: sty.box ? sty.box_color : undefined,
                  padding: sty.box ? '0 4px' : undefined,
                  fontSize: 13,
                }}
              >
                Clip <span style={{ color: sty.highlight_color }}>this</span>
              </span>
              <span className="mt-1 text-[10px] text-ink-300">{sty.name ?? id}</span>
            </button>
          ))}
        </div>
      </Section>
      <Section title="Customize">
        <div className="flex flex-col gap-2.5">
          <Field label="Font">
            <Select value={st.font} onChange={(v) => setStyle('font', v, false)} options={[...new Set([st.font, ...(fonts.data ?? [])])].map((f) => ({ value: f, label: f }))} />
          </Field>
          <Slider label="Size" value={st.size} min={0.02} max={0.1} step={0.002} format={(v) => `${(v * 100).toFixed(1)}%`} onChange={(v) => setStyle('size', v)} />
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            <Color label="Text" value={st.color} onChange={(v) => setStyle('color', v)} />
            <Color label="Highlight" value={st.highlight_color} onChange={(v) => setStyle('highlight_color', v)} />
            <Color label="Stroke" value={st.stroke_color} onChange={(v) => setStyle('stroke_color', v)} />
            <Color label="Shadow" value={st.shadow_color} onChange={(v) => setStyle('shadow_color', v)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Slider label="Stroke width" value={Number(st.stroke)} min={0} max={10} step={0.5} onChange={(v) => setStyle('stroke', v)} />
            <Slider label="Shadow" value={Number(st.shadow)} min={0} max={8} step={0.5} onChange={(v) => setStyle('shadow', v)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Position">
              <Select value={st.position} onChange={(v) => setStyle('position', v, false)} options={POSITIONS} />
            </Field>
            <Field label="Animation">
              <Select value={st.animation} onChange={(v) => setStyle('animation', v, false)} options={ANIMS} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Slider label="Margin" value={Number(st.margin)} min={0} max={0.45} step={0.01} format={(v) => `${Math.round(v * 100)}%`} onChange={(v) => setStyle('margin', v)} />
            <Slider label="Line spacing" value={Number(st.line_spacing ?? 1)} min={0.8} max={1.6} step={0.05} format={(v) => v.toFixed(2)} onChange={(v) => setStyle('line_spacing', v)} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Toggle checked={!!st.bold} onChange={(v) => setStyle('bold', v, false)} label="Bold" />
            <Toggle checked={!!st.uppercase} onChange={(v) => setStyle('uppercase', v, false)} label="Uppercase" />
            <Toggle checked={!!st.highlight_keywords} onChange={(v) => setStyle('highlight_keywords', v, false)} label="Keyword highlight" />
            <Toggle checked={!!st.box} onChange={(v) => setStyle('box', v, false)} label="Background box" />
          </div>
          {st.box && (
            <div className="grid grid-cols-2 gap-3">
              <Color label="Box color" value={st.box_color} onChange={(v) => setStyle('box_color', v)} />
              <Slider label="Box opacity" value={Number(st.box_opacity ?? 0.5)} min={0} max={1} step={0.05} format={(v) => `${Math.round(v * 100)}%`} onChange={(v) => setStyle('box_opacity', v)} />
            </div>
          )}
          <div className="flex items-end gap-2 border-t border-ink-600 pt-2.5">
            <div className="flex-1">
              <Slider label="Words per caption" value={wpc} min={1} max={15} step={1} onChange={setWpc} />
            </div>
            <Button size="sm" variant="subtle" loading={busy} icon={<Wand2 className="h-3.5 w-3.5" />} onClick={rebuild}>
              Rebuild from transcript
            </Button>
          </div>
        </div>
      </Section>
      <Section title={`Captions (${captions.items.length})`}>
        <div ref={listRef} className="flex flex-col gap-1.5">
          {captions.items.length === 0 && <div className="text-2xs text-ink-300">No captions. Use “Rebuild from transcript”.</div>}
          {captions.items.map((it, idx) => {
            const active = it.start <= time && time < it.end;
            const sel = selCaption === it.id;
            return (
              <div
                key={it.id}
                data-cap={it.id}
                className={cx('rounded-md border p-2', sel ? 'border-sky-400/70 bg-sky-500/5' : active ? 'border-amber-500/40 bg-ink-850' : 'border-ink-600 bg-ink-850')}
                onClick={() => setStore({ selCaption: it.id })}
              >
                <div className="flex items-center gap-1 text-2xs">
                  <button
                    className="font-mono text-ink-200 hover:text-amber-400"
                    onClick={() => {
                      player.pause();
                      player.seek(it.start);
                    }}
                  >
                    {fmtTime(it.start, true)}
                  </button>
                  <Nudge
                    onNudge={(d) =>
                      updItem(
                        it.id,
                        (x) => {
                          const minS = captions.items[idx - 1]?.end ?? 0;
                          const maxS = x.end - 0.12;
                          if (maxS >= minS) x.start = round3(Math.max(minS, Math.min(maxS, x.start + d)));
                        },
                        `ns-${it.id}`,
                      )
                    }
                  />
                  <span className="text-ink-400">→</span>
                  <span className="font-mono text-ink-200">{fmtTime(it.end, true)}</span>
                  <Nudge
                    onNudge={(d) =>
                      updItem(
                        it.id,
                        (x) => {
                          const minE = x.start + 0.12;
                          const maxE = captions.items[idx + 1]?.start ?? Infinity;
                          if (maxE >= minE) x.end = round3(Math.min(maxE, Math.max(minE, x.end + d)));
                        },
                        `ne-${it.id}`,
                      )
                    }
                  />
                  <div className="flex-1" />
                  <IconButton title="Split caption (at playhead word if inside)" className="h-5 w-5" onClick={() => split(idx)}>
                    <Scissors className="h-3 w-3" />
                  </IconButton>
                  <IconButton title="Merge with next" className="h-5 w-5" disabled={idx >= captions.items.length - 1} onClick={() => merge(idx)}>
                    <Merge className="h-3 w-3" />
                  </IconButton>
                  <IconButton title="Delete caption" className="h-5 w-5" onClick={() => commit((s) => ((s.captions.items = s.captions.items.filter((x) => x.id !== it.id)), s))}>
                    <Trash2 className="h-3 w-3" />
                  </IconButton>
                </div>
                <textarea
                  aria-label={`Caption ${idx + 1} text`}
                  lang={/[\u0900-\u097F]/.test(it.text) ? 'hi' : undefined}
                  style={{ fontFamily: '"Segoe UI", "Nirmala UI", sans-serif' }}
                  className="mt-1 w-full resize-none rounded border border-ink-600 bg-ink-900 px-1.5 py-1 text-xs text-ink-50 focus:border-amber-500/60 focus:outline-none"
                  rows={Math.min(4, it.text.split('\n').length + (it.text.length > 40 ? 1 : 0))}
                  value={it.text}
                  maxLength={500}
                  onChange={(e) => updItem(it.id, (x) => (x.text = e.target.value), `txt-${it.id}`)}
                  title="Enter inserts a manual line break"
                />
                {sel && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 border-t border-ink-650 pt-1.5 text-2xs text-ink-300">
                    <span>Override:</span>
                    <label className="flex items-center gap-1">
                      color
                      <input type="color" value={it.style?.color ?? st.color} onChange={(e) => updItem(it.id, (x) => (x.style = { ...x.style, color: e.target.value.toUpperCase() }), `oc-${it.id}`)} />
                    </label>
                    <label className="flex items-center gap-1">
                      size
                      <input
                        type="range"
                        className="cf-range w-20"
                        min={0.02}
                        max={0.1}
                        step={0.002}
                        value={it.style?.size ?? st.size}
                        onChange={(e) => updItem(it.id, (x) => (x.style = { ...x.style, size: Number(e.target.value) }), `os-${it.id}`)}
                      />
                    </label>
                    <select
                      className="h-6 rounded border border-ink-600 bg-ink-900 px-1 text-2xs text-ink-100"
                      value={it.style?.position ?? ''}
                      onChange={(e) => updItem(it.id, (x) => (x.style = { ...x.style, position: (e.target.value || undefined) as CaptionPosition | undefined }))}
                    >
                      <option value="">position: default</option>
                      {POSITIONS.map((p) => (
                        <option key={p.value} value={p.value}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                    {Object.keys(it.style ?? {}).length > 0 && (
                      <button className="flex items-center gap-0.5 text-ink-300 hover:text-ink-50" onClick={() => updItem(it.id, (x) => (x.style = {}))}>
                        <RotateCcw className="h-3 w-3" /> reset
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

function Nudge({ onNudge }: { onNudge: (d: number) => void }) {
  return (
    <span className="inline-flex items-center rounded border border-ink-600">
      <button className="px-1 text-ink-300 hover:text-ink-50" title="-0.1s" onClick={(e) => (e.stopPropagation(), onNudge(-0.1))}>
        ‹
      </button>
      <ChevronsLeftRight className="h-2.5 w-2.5 text-ink-500" />
      <button className="px-1 text-ink-300 hover:text-ink-50" title="+0.1s" onClick={(e) => (e.stopPropagation(), onNudge(0.1))}>
        ›
      </button>
    </span>
  );
}
