import { FileVideo, FolderOpen, HardDriveUpload, Link2, Loader2, UploadCloud, X, Youtube } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, errMsg, type UploadHandle } from '../api';
import { AnalysisOptions, defaultAnalysisOptions, toAnalyzeParams, type AnalysisOptionsValue } from '../components/AnalysisOptions';
import { PageHeader } from '../components/PageHeader';
import { Button, Field, inputCls, Panel, ProgressBar, Segmented, Toggle } from '../components/ui';
import { cx, fmtBytes } from '../lib/format';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';

type Source = 'upload' | 'local' | 'youtube';
const VIDEO_EXT = /\.(mp4|mov|mkv|webm|avi|m4v|wmv|flv|ts|mts|m2ts|mpg|mpeg|mp3|wav|m4a|flac|aac|ogg|opus)$/i;

export function NewProjectPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { settings, load } = useSettings();
  const [name, setName] = useState('');
  const [source, setSource] = useState<Source>(params.get('source') === 'local' ? 'local' : params.get('source') === 'youtube' ? 'youtube' : 'upload');
  const [file, setFile] = useState<File | null>(null);
  const [localPath, setLocalPath] = useState('');
  const [copyFile, setCopyFile] = useState(true);
  const [ytUrl, setYtUrl] = useState('');
  const [ytConfirm, setYtConfirm] = useState(false);
  const [opts, setOpts] = useState<AnalysisOptionsValue>(defaultAnalysisOptions(settings));
  const [optsTouched, setOptsTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState<{ loaded: number; total: number } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const handle = useRef<UploadHandle | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!settings) void load();
  }, [settings, load]);
  useEffect(() => {
    if (settings && !optsTouched) {
      setOpts(defaultAnalysisOptions(settings));
      setCopyFile(settings.copy_imports);
    }
  }, [settings, optsTouched]);
  useEffect(() => () => handle.current?.abort(), []);

  const pickLocal = async () => {
    try {
      const r = await api.dialog('file', 'Select a video to import');
      if (r.path) {
        setLocalPath(r.path);
        if (!name) setName(baseName(r.path));
      }
    } catch (e) {
      toast.error('File dialog failed', errMsg(e));
    }
  };

  const chooseFile = (f: File | undefined | null) => {
    if (!f) return;
    if (!VIDEO_EXT.test(f.name)) {
      toast.error('Unsupported file type', `${f.name} is not a supported video or audio file.`);
      return;
    }
    setFile(f);
    if (!name) setName(f.name.replace(/\.[^.]+$/, ''));
  };

  const canStart =
    !busy &&
    opts.duration_targets.length > 0 &&
    ((source === 'upload' && !!file) || (source === 'local' && localPath.trim().length > 3) || (source === 'youtube' && ytUrl.trim().length > 10 && ytConfirm));

  const start = async () => {
    setBusy(true);
    let projectId: string | null = null;
    try {
      const pname = name.trim() || (source === 'youtube' ? 'YouTube import' : source === 'upload' && file ? file.name.replace(/\.[^.]+$/, '') : baseName(localPath)) || 'Untitled project';
      const analysis = toAnalyzeParams(opts);
      // Discovery options are persisted on the project so auto-analysis after upload uses them.
      const project = await api.createProject(pname, { ...analysis, max_clips_per_target: settings?.max_clips_per_target });
      projectId = project.id;
      if (source === 'upload' && file) {
        setUpload({ loaded: 0, total: file.size });
        const h = api.uploadMedia(project.id, file, opts.auto_analyze, (loaded, total) => setUpload({ loaded, total }));
        handle.current = h;
        await h.promise;
        handle.current = null;
      } else if (source === 'local') {
        await api.importPath(project.id, { path: localPath.trim(), copy_file: copyFile, auto_analyze: opts.auto_analyze, analysis_params: analysis });
      } else {
        await api.importYoutube(project.id, { url: ytUrl.trim(), confirm_rights: ytConfirm, auto_analyze: opts.auto_analyze, analysis_params: analysis });
      }
      toast.success('Import started', opts.auto_analyze ? 'Analysis will start automatically when the import finishes.' : undefined);
      nav(`/projects/${project.id}`);
    } catch (e) {
      toast.error('Import failed', errMsg(e));
      setUpload(null);
      if (projectId) {
        // clean up the empty project so failed imports don't litter the list
        try {
          await api.deleteProject(projectId, false);
        } catch {
          /* ignore */
        }
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="New project" subtitle="Import a long-form video, choose what kind of clips you want, and let the local pipeline find them." />
      <div className="mx-auto grid max-w-[1200px] grid-cols-1 gap-4 p-6 lg:grid-cols-[1fr_1fr]">
        <div className="flex flex-col gap-4">
          <Panel title="1 · Project">
            <Field label="Project name">
              <input className={inputCls} placeholder="e.g. Episode 371 — Cord Killers" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
            </Field>
          </Panel>
          <Panel title="2 · Source video">
            <div className="mb-3">
              <Segmented
                value={source}
                onChange={setSource}
                options={[
                  { value: 'upload', label: <span className="flex items-center gap-1.5"><UploadCloud className="h-3.5 w-3.5" /> Upload</span> },
                  { value: 'local', label: <span className="flex items-center gap-1.5"><HardDriveUpload className="h-3.5 w-3.5" /> Local file</span> },
                  { value: 'youtube', label: <span className="flex items-center gap-1.5"><Youtube className="h-3.5 w-3.5" /> YouTube</span> },
                ]}
              />
            </div>
            {source === 'upload' && (
              <div>
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOver(false);
                    chooseFile(e.dataTransfer.files?.[0]);
                  }}
                  onClick={() => fileInput.current?.click()}
                  className={cx(
                    'flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors',
                    dragOver ? 'border-amber-500 bg-amber-500/5' : 'border-ink-500 bg-ink-850 hover:border-ink-400',
                  )}
                >
                  <UploadCloud className="mb-2 h-8 w-8 text-ink-300" />
                  <div className="text-sm text-ink-100">Drop a video here or click to browse</div>
                  <div className="mt-1 text-2xs text-ink-300">MP4, MOV, MKV, WEBM, AVI… streamed to the local backend — nothing leaves this PC.</div>
                  <input ref={fileInput} type="file" accept="video/*,audio/*,.mkv,.mts,.ts" className="hidden" onChange={(e) => chooseFile(e.target.files?.[0])} />
                </div>
                {file && (
                  <div className="mt-3 flex items-center gap-2 rounded-md border border-ink-600 bg-ink-850 p-2.5">
                    <FileVideo className="h-4 w-4 text-amber-400" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs text-ink-50">{file.name}</div>
                      <div className="text-2xs text-ink-300">{fmtBytes(file.size)}</div>
                    </div>
                    {!busy && (
                      <button className="text-ink-300 hover:text-ink-50" onClick={() => setFile(null)} aria-label="Remove file">
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                )}
                {upload && (
                  <div className="mt-3">
                    <ProgressBar value={upload.total ? upload.loaded / upload.total : 0} />
                    <div className="mt-1 flex justify-between text-2xs text-ink-300">
                      <span>
                        Uploading {fmtBytes(upload.loaded)} / {fmtBytes(upload.total)}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="font-mono">{upload.total ? ((upload.loaded / upload.total) * 100).toFixed(0) : 0}%</span>
                        <button className="text-red-300 hover:text-red-200" onClick={() => handle.current?.abort()}>
                          Cancel
                        </button>
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}
            {source === 'local' && (
              <div className="flex flex-col gap-3">
                <Field label="File path" hint="Use the native picker, or paste a full path to a video on this PC.">
                  <div className="flex gap-1.5">
                    <input className={inputCls} placeholder="C:\Videos\episode.mp4" value={localPath} onChange={(e) => setLocalPath(e.target.value)} />
                    <Button variant="primary" icon={<FolderOpen className="h-3.5 w-3.5" />} onClick={pickLocal}>
                      Pick local file
                    </Button>
                  </div>
                </Field>
                <Toggle
                  checked={copyFile}
                  onChange={setCopyFile}
                  label="Copy into project folder"
                  hint={copyFile ? 'A copy is stored with the project (safe if the original moves).' : 'The original file is referenced in place — no extra disk space, but don’t move or delete it.'}
                />
              </div>
            )}
            {source === 'youtube' && (
              <div className="flex flex-col gap-3">
                <Field label="YouTube URL">
                  <div className="relative">
                    <Link2 className="absolute left-2.5 top-2 h-3.5 w-3.5 text-ink-400" />
                    <input className={`${inputCls} pl-8`} placeholder="https://www.youtube.com/watch?v=…" value={ytUrl} onChange={(e) => setYtUrl(e.target.value)} />
                  </div>
                </Field>
                <label className="flex cursor-pointer items-start gap-2 text-xs text-ink-100">
                  <input type="checkbox" className="mt-0.5 accent-amber-500" checked={ytConfirm} onChange={(e) => setYtConfirm(e.target.checked)} />
                  <span>
                    I own this content or am authorized to download it. <span className="text-ink-300">(Required)</span>
                  </span>
                </label>
                <div className="rounded-md border border-ink-600 bg-ink-850 p-2.5 text-2xs leading-relaxed text-ink-300">
                  Videos requiring sign-in, age verification or DRM are not downloaded. If a download fails, download the file yourself (if authorized) and use <b className="text-ink-100">Upload</b> or <b className="text-ink-100">Local file</b> instead. YouTube import is disabled in offline mode.
                </div>
              </div>
            )}
          </Panel>
        </div>
        <div className="flex flex-col gap-4">
          <Panel title="3 · Analysis options">
            <AnalysisOptions
              value={opts}
              compact
              onChange={(v) => {
                setOptsTouched(true);
                setOpts(v);
              }}
            />
          </Panel>
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="md" onClick={() => nav(-1)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" size="md" disabled={!canStart} onClick={start} icon={busy ? <Loader2 className="h-4 w-4 animate-spin" /> : undefined}>
              {opts.auto_analyze ? 'Import & analyze' : 'Import'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function baseName(p: string): string {
  return (p.split(/[\\/]/).pop() ?? '').replace(/\.[^.]+$/, '');
}
