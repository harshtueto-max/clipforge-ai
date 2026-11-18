import { Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import { fmtBytes, fmtDur } from '../lib/format';
import type { Analysis, Project } from '../types';
import { Badge, Stat } from './ui';

export function SourceInfo({ project }: { project: Project }) {
  const m = project.media;
  if (!m) return <div className="text-xs text-ink-300">No media imported yet.</div>;
  return (
    <div className="grid grid-cols-3 gap-x-3 gap-y-2.5">
      <Stat label="Resolution" value={m.has_video ? `${m.width}×${m.height}` : 'audio only'} />
      <Stat label="Frame rate" value={m.fps ? `${m.fps.toFixed(2)} fps` : '—'} />
      <Stat label="Duration" value={fmtDur(m.duration)} />
      <Stat label="Video codec" value={m.video_codec ?? '—'} />
      <Stat label="Audio codec" value={m.audio_codec ?? '—'} />
      <Stat label="Size" value={fmtBytes(m.size_bytes)} />
      <div className="col-span-3 min-w-0">
        <div className="text-2xs uppercase tracking-wider text-ink-300">File</div>
        <div className="truncate text-xs text-ink-100" title={m.original_name}>
          {m.original_name}
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          <Badge>{m.is_reference ? 'referenced in place' : 'copied to project'}</Badge>
          {m.proxy_ready && <Badge tone="blue">preview proxy</Badge>}
          {m.source_url && <Badge tone="red">YouTube</Badge>}
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-ink-650 py-1.5 text-xs last:border-0">
      <span className="shrink-0 text-ink-300">{k}</span>
      <span className="min-w-0 text-right text-ink-100">{v}</span>
    </div>
  );
}

export function AnalysisSummaryView({ project, analysis }: { project: Project; analysis: Analysis | null }) {
  const st = project.analysis_summary?.stages;
  if (!st) return <div className="text-xs text-ink-300">Not analyzed yet. Run the analysis to transcribe, detect speakers, scenes and discover clips.</div>;
  const kw = (analysis?.keywords ?? st.semantic?.keywords ?? []).map((k) => (typeof k === 'string' ? k : Array.isArray(k) ? String(k[0]) : String(Object.values(k)[0]))).slice(0, 20);
  return (
    <div>
      {st.transcribe && (
        <Row k="Transcript" v={`${st.transcribe.language?.toUpperCase()} · ${st.transcribe.words.toLocaleString()} words · ${st.transcribe.model} on ${st.transcribe.device ?? 'cpu'}${st.transcribe.elapsed_s ? ` · ${fmtDur(st.transcribe.elapsed_s)}` : ''}`} />
      )}
      {st.diarization && <Row k="Speakers" v={`${st.diarization.speakers} (${st.diarization.method})`} />}
      {analysis?.speakers?.length ? (
        <Row k="Speaking time" v={analysis.speakers.map((s) => `${s.label}: ${fmtDur(Number(s.speaking_time))}`).join(' · ')} />
      ) : null}
      {st.vision && <Row k="Scenes / faces" v={`${st.vision.scenes} scenes · faces visible ${Math.round(st.vision.face_visible_ratio * 100)}%${st.vision.detector ? ` · ${st.vision.detector}` : ''}`} />}
      {st.audio_analysis && (
        <Row k="Audio" v={`${st.audio_analysis.laughter_events} laughter · ${st.audio_analysis.excitement_peaks} excitement peaks · speech ${Math.round(st.audio_analysis.speech_ratio * 100)}%`} />
      )}
      {st.semantic && <Row k="Topics" v={`${st.semantic.topics} topic segments`} />}
      {st.discovery && (
        <Row
          k="Discovery"
          v={
            <span>
              {st.discovery.candidates} clips for {st.discovery.targets.join(', ')}s (±{Math.round(st.discovery.tolerance * 100)}%) · {st.discovery.source}
              {st.discovery.unfit_targets?.length ? <span className="block text-amber-300">No good fit for: {st.discovery.unfit_targets.join(', ')}s</span> : null}
              {st.discovery.llm && <span className="block text-ink-300">{st.discovery.llm}</span>}
            </span>
          }
        />
      )}
      {project.analysis_summary.elapsed_s ? <Row k="Total time" v={fmtDur(project.analysis_summary.elapsed_s)} /> : null}
      {kw.length > 0 && (
        <div className="mt-2">
          <div className="mb-1 flex items-center gap-1 text-2xs uppercase tracking-wider text-ink-300">
            <Sparkles className="h-3 w-3" /> Keywords
          </div>
          <div className="flex flex-wrap gap-1">
            {kw.map((k) => (
              <Badge key={k}>{k}</Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
