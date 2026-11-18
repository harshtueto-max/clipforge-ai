import { FolderOpen, Grid2x2, List, Pencil, Plus, Search, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, errMsg } from '../api';
import { PageHeader } from '../components/PageHeader';
import { Thumb } from '../components/Thumb';
import { Button, ConfirmDialog, EmptyState, ErrorState, IconButton, inputCls, LoadingBlock, Modal, Segmented, StatusBadge, Toggle } from '../components/ui';
import { fmtBytes, fmtDate, fmtDur } from '../lib/format';
import { useFetch, useWsEvent } from '../lib/hooks';
import { toast } from '../stores/toast';
import type { Project } from '../types';

export function ProjectsPage() {
  const nav = useNavigate();
  const q = useFetch(() => api.projects(), []);
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [search, setSearch] = useState('');
  const [rename, setRename] = useState<Project | null>(null);
  const [del, setDel] = useState<Project | null>(null);
  const [delExports, setDelExports] = useState(false);
  useWsEvent((m) => {
    if (m.type === 'project' || m.type === 'clips') void q.reload(true);
  });
  const list = (q.data ?? []).filter((p) => p.name.toLowerCase().includes(search.toLowerCase()));
  const doDelete = async () => {
    if (!del) return;
    try {
      await api.deleteProject(del.id, delExports);
      toast.success('Project deleted', del.name);
      await q.reload(true);
    } catch (e) {
      toast.error('Delete failed', errMsg(e));
    }
  };
  const actions = (p: Project) => (
    <div className="flex items-center gap-0.5">
      <IconButton title="Rename" onClick={(e) => (e.preventDefault(), setRename(p))}>
        <Pencil className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton
        title="Delete"
        onClick={(e) => {
          e.preventDefault();
          setDelExports(false);
          setDel(p);
        }}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </IconButton>
    </div>
  );
  return (
    <div>
      <PageHeader
        title="Projects"
        subtitle={q.data ? `${q.data.length} project(s)` : undefined}
        actions={
          <>
            <Button variant="ghost" icon={<FolderOpen className="h-3.5 w-3.5" />} onClick={() => api.openFolder('projects').catch((e) => toast.error('Could not open folder', errMsg(e)))}>
              Open folder
            </Button>
            <Button variant="primary" size="md" icon={<Plus className="h-4 w-4" />} onClick={() => nav('/new')}>
              New Project
            </Button>
          </>
        }
      >
        <div className="mt-3 flex items-center gap-2">
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-ink-400" />
            <input className={`${inputCls} pl-8`} placeholder="Search projects" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: 'grid', label: <Grid2x2 className="h-3.5 w-3.5" />, title: 'Grid' },
              { value: 'list', label: <List className="h-3.5 w-3.5" />, title: 'List' },
            ]}
          />
        </div>
      </PageHeader>
      <div className="p-6">
        {q.loading && !q.data ? (
          <LoadingBlock />
        ) : q.error ? (
          <ErrorState message={q.error} onRetry={() => q.reload()} />
        ) : !list.length ? (
          <EmptyState title={search ? 'No matching projects' : 'No projects yet'} action={!search && <Button variant="primary" onClick={() => nav('/new')}>New project</Button>} />
        ) : view === 'grid' ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
            {list.map((p) => (
              <Link key={p.id} to={`/projects/${p.id}`} className="group overflow-hidden rounded-lg border border-ink-600 bg-ink-800 hover:border-ink-400">
                <Thumb src={p.has_thumbnail ? `/api/projects/${p.id}/thumbnail?v=${encodeURIComponent(p.updated_at)}` : null} alt={p.name} className="aspect-video">
                  {p.media && <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 font-mono text-[10px]">{fmtDur(p.media.duration)}</span>}
                </Thumb>
                <div className="p-2.5">
                  <div className="flex items-start gap-1">
                    <div className="min-w-0 flex-1 truncate text-xs font-medium text-ink-50 group-hover:text-amber-300">{p.name}</div>
                    {actions(p)}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-2xs text-ink-300">
                    <StatusBadge status={p.status} />
                    <span>{p.clip_count} clips</span>
                    <span>{p.accepted_count} accepted</span>
                  </div>
                  <div className="mt-1 text-[10px] text-ink-400">Updated {fmtDate(p.updated_at)}</div>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-ink-600">
            <table className="w-full text-xs">
              <thead className="bg-ink-800 text-left text-2xs uppercase tracking-wider text-ink-300">
                <tr>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Source</th>
                  <th className="px-3 py-2">Clips</th>
                  <th className="px-3 py-2">Exports</th>
                  <th className="px-3 py-2">Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.map((p) => (
                  <tr key={p.id} className="cursor-pointer border-t border-ink-600 hover:bg-ink-800" onClick={() => nav(`/projects/${p.id}`)}>
                    <td className="px-3 py-2 font-medium text-ink-50">{p.name}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={p.status} />
                    </td>
                    <td className="px-3 py-2 text-ink-300">{p.media ? `${p.media.width}×${p.media.height} · ${fmtDur(p.media.duration)} · ${fmtBytes(p.media.size_bytes)}` : '—'}</td>
                    <td className="px-3 py-2 text-ink-200">
                      {p.clip_count} <span className="text-ink-400">({p.accepted_count} accepted)</span>
                    </td>
                    <td className="px-3 py-2 text-ink-200">{p.export_count}</td>
                    <td className="px-3 py-2 text-ink-300">{fmtDate(p.updated_at)}</td>
                    <td className="px-2 py-1" onClick={(e) => e.stopPropagation()}>
                      {actions(p)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <RenameModal project={rename} onClose={() => setRename(null)} onDone={() => q.reload(true)} />
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} title="Delete project" danger confirmLabel="Delete project" message={<>Delete <b>{del?.name}</b>, its analysis, clips and edits? Referenced original files are never deleted.</>} onConfirm={doDelete}>
        <Toggle checked={delExports} onChange={setDelExports} label="Also delete exported video files" />
      </ConfirmDialog>
    </div>
  );
}

function RenameModal({ project, onClose, onDone }: { project: Project | null; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [lastId, setLastId] = useState<string | null>(null);
  if (project && project.id !== lastId) {
    setLastId(project.id);
    setName(project.name);
  }
  const save = async () => {
    if (!project || !name.trim()) return;
    setBusy(true);
    try {
      await api.updateProject(project.id, { name: name.trim() });
      toast.success('Project renamed');
      onDone();
      onClose();
    } catch (e) {
      toast.error('Rename failed', errMsg(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={!!project}
      onClose={() => {
        setLastId(null);
        onClose();
      }}
      title="Rename project"
      width={420}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      <input className={inputCls} value={name} maxLength={200} autoFocus onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && save()} />
    </Modal>
  );
}
