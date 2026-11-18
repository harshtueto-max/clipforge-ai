import { CheckCircle2, KeyRound, Plug, Plus, ShieldCheck, Trash2, XCircle } from 'lucide-react';
import { useState } from 'react';
import { api, errMsg } from '../../api';
import { useFetch } from '../../lib/hooks';
import { useSettings } from '../../stores/settings';
import { toast } from '../../stores/toast';
import type { PrivacySummary, Provider, ProviderKind } from '../../types';
import { Badge, Button, ConfirmDialog, EmptyState, ErrorState, Field, inputCls, LoadingBlock, Modal, Panel, Select, Toggle } from '../ui';

export function ProvidersSection() {
  const providers = useFetch(() => api.providers(), []);
  const kinds = useFetch(() => api.providerKinds(), []);
  const privacy = useFetch(() => api.privacySummary(), []);
  const settings = useSettings((s) => s.settings);
  const [adding, setAdding] = useState(false);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [privacyFor, setPrivacyFor] = useState<Provider | null>(null);
  const [del, setDel] = useState<Provider | null>(null);
  const update = (p: Provider) => providers.setData((prev) => (prev ? prev.map((x) => (x.id === p.id ? p : x)) : prev));

  const enable = async (p: Provider, on: boolean) => {
    if (on && !p.is_local && !p.privacy_acknowledged) {
      setPrivacyFor(p);
      return;
    }
    try {
      update(await api.updateProvider(p.id, { enabled: on }));
      toast.success(on ? `${p.name} enabled` : `${p.name} disabled`);
    } catch (e) {
      toast.error('Could not update provider', errMsg(e));
    }
  };
  const acknowledgeAndEnable = async () => {
    if (!privacyFor) return;
    try {
      await api.acknowledgeProvider(privacyFor.id);
      update(await api.updateProvider(privacyFor.id, { enabled: true }));
      toast.success(`${privacyFor.name} enabled`);
    } catch (e) {
      toast.error('Could not enable provider', errMsg(e));
      await providers.reload(true);
    }
  };
  const test = async (p: Provider) => {
    try {
      const r = await api.testProvider(p.id);
      update(r);
      if (r.models) setModels((m) => ({ ...m, [p.id]: r.models ?? [] }));
      if (r.last_test.ok) toast.success(`Connected to ${p.name}`, `${r.last_test.latency_ms ?? '?'} ms · ${r.models?.length ?? 0} models`);
      else toast.error(`${p.name} test failed`, String(r.last_test.error ?? 'Unknown error'));
    } catch (e) {
      toast.error('Test failed', errMsg(e));
    }
  };
  const remove = async () => {
    if (!del) return;
    try {
      await api.deleteProvider(del.id);
      toast.success('Provider removed');
      await providers.reload(true);
    } catch (e) {
      toast.error('Delete failed', errMsg(e));
    }
  };

  if (providers.loading && !providers.data) return <LoadingBlock />;
  if (providers.error) return <ErrorState message={providers.error} onRetry={() => providers.reload()} />;
  return (
    <div className="flex flex-col gap-4">
      <Panel title="AI providers" actions={<Button size="xs" variant="primary" icon={<Plus className="h-3 w-3" />} onClick={() => setAdding(true)}>Add provider</Button>}>
        <div className="mb-3 text-2xs leading-relaxed text-ink-300">
          Optional: an LLM can refine titles, hooks and clip boundaries after local analysis. Local providers (Ollama, LM Studio on localhost) keep everything on this PC. Cloud providers are off by default and require reviewing the privacy summary.
          {settings?.offline_mode && <span className="ml-1 text-emerald-300">Offline mode is on — cloud providers can’t be enabled.</span>}
        </div>
        {!providers.data?.length ? (
          <EmptyState icon={<Plug className="h-6 w-6" />} title="No AI providers configured">Clip discovery works fully offline without one.</EmptyState>
        ) : (
          <div className="flex flex-col gap-2">
            {providers.data.map((p) => (
              <ProviderCard key={p.id} p={p} kind={kinds.data?.[p.kind]} models={models[p.id]} onUpdate={update} onEnable={(on) => enable(p, on)} onTest={() => test(p)} onDelete={() => setDel(p)} />
            ))}
          </div>
        )}
      </Panel>
      {adding && kinds.data && <AddProviderModal kinds={kinds.data} onClose={() => setAdding(false)} onDone={() => providers.reload(true)} />}
      <PrivacyModal provider={privacyFor} summary={privacy.data} onClose={() => setPrivacyFor(null)} onConfirm={acknowledgeAndEnable} />
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} title="Remove provider" danger confirmLabel="Remove" message={`Remove ${del?.name}? Its stored API key is deleted too.`} onConfirm={remove} />
    </div>
  );
}

function ProviderCard({ p, kind, models, onUpdate, onEnable, onTest, onDelete }: { p: Provider; kind?: ProviderKind; models?: string[]; onUpdate: (p: Provider) => void; onEnable: (on: boolean) => void; onTest: () => Promise<void>; onDelete: () => void }) {
  const [key, setKey] = useState('');
  const [url, setUrl] = useState(p.base_url ?? '');
  const [model, setModel] = useState(p.model);
  const [testing, setTesting] = useState(false);
  const [framesWarn, setFramesWarn] = useState(false);
  const patch = async (body: Parameters<typeof api.updateProvider>[1], ok?: string) => {
    try {
      onUpdate(await api.updateProvider(p.id, body));
      if (ok) toast.success(ok);
    } catch (e) {
      toast.error('Could not update provider', errMsg(e));
    }
  };
  const lt = p.last_test;
  return (
    <div className="rounded-md border border-ink-600 bg-ink-850 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ink-50">{p.name}</span>
        <Badge>{kind?.label ?? p.kind}</Badge>
        {p.is_local ? <Badge tone="green">local</Badge> : <Badge tone="amber">cloud</Badge>}
        {p.has_key && (
          <Badge tone="blue">
            <KeyRound className="h-3 w-3" /> key stored
          </Badge>
        )}
        {!p.is_local && p.privacy_acknowledged && (
          <Badge tone="green">
            <ShieldCheck className="h-3 w-3" /> privacy reviewed
          </Badge>
        )}
        <div className="flex-1" />
        <Toggle checked={p.enabled} onChange={onEnable} label="Enabled" />
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        <Field label="Base URL">
          <input className={inputCls} value={url} onChange={(e) => setUrl(e.target.value)} onBlur={() => url !== (p.base_url ?? '') && patch({ base_url: url }, 'URL updated')} />
        </Field>
        <Field label="Model">
          {models && models.length ? (
            <Select value={model} onChange={(v) => (setModel(v), patch({ model: v }, 'Model updated'))} options={[...new Set([model, ...models])].filter(Boolean).map((m) => ({ value: m, label: m }))} />
          ) : (
            <input className={inputCls} value={model} placeholder={kind?.default_model} onChange={(e) => setModel(e.target.value)} onBlur={() => model !== p.model && patch({ model }, 'Model updated')} />
          )}
        </Field>
        <Field label={`API key${kind?.needs_key ? ' (required)' : ''}`} hint={p.has_key ? 'A key is stored (encrypted). Enter a new one to replace it.' : 'Write-only — never shown again after saving.'}>
          <div className="flex gap-1">
            <input className={inputCls} type="password" autoComplete="off" value={key} placeholder={p.has_key ? '••••••••  (stored)' : 'sk-…'} onChange={(e) => setKey(e.target.value)} />
            <Button size="sm" variant="subtle" disabled={!key} onClick={async () => (await patch({ api_key: key }, 'API key saved'), setKey(''))}>
              Save
            </Button>
            {p.has_key && (
              <Button size="sm" variant="ghost" onClick={() => patch({ clear_key: true }, 'API key removed')}>
                Clear
              </Button>
            )}
          </div>
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button size="sm" variant="secondary" loading={testing} icon={<Plug className="h-3.5 w-3.5" />} onClick={async () => (setTesting(true), await onTest(), setTesting(false))}>
          Test connection
        </Button>
        {lt && lt.at ? (
          lt.ok ? (
            <span className="flex items-center gap-1 text-2xs text-emerald-300">
              <CheckCircle2 className="h-3.5 w-3.5" /> OK · {String(lt.latency_ms ?? '?')} ms
            </span>
          ) : (
            <span className="flex max-w-md items-center gap-1 truncate text-2xs text-red-300" title={String(lt.error ?? '')}>
              <XCircle className="h-3.5 w-3.5 shrink-0" /> {String(lt.error ?? 'failed')}
            </span>
          )
        ) : null}
        {!p.is_local && (
          <Toggle
            checked={p.send_frames}
            onChange={(v) => (v ? setFramesWarn(true) : patch({ send_frames: false }, 'Frames will not be sent'))}
            label="Send video frames"
            hint="Allows sharing selected still frames (512px JPEG) for visual context"
          />
        )}
        <div className="flex-1" />
        <span className="text-2xs text-ink-300">
          Usage: {p.usage.requests ?? 0} requests · {(p.usage.input_tokens ?? 0).toLocaleString()} in / {(p.usage.output_tokens ?? 0).toLocaleString()} out tokens
        </span>
        <Button size="xs" variant="ghost" icon={<Trash2 className="h-3 w-3" />} onClick={onDelete}>
          Remove
        </Button>
      </div>
      <ConfirmDialog
        open={framesWarn}
        onClose={() => setFramesWarn(false)}
        title="Send video frames to this provider?"
        confirmLabel="Allow frames"
        message="Selected still frames from your video will be uploaded to this cloud provider during analysis. Because this widens what is shared, the provider is disabled until you review the privacy summary and enable it again."
        onConfirm={() => patch({ send_frames: true }, 'Frames enabled — re-enable the provider after reviewing privacy')}
      />
    </div>
  );
}

function AddProviderModal({ kinds, onClose, onDone }: { kinds: Record<string, ProviderKind>; onClose: () => void; onDone: () => void }) {
  const [kind, setKind] = useState<string>('ollama');
  const k = kinds[kind];
  const [name, setName] = useState(k?.label ?? '');
  const [url, setUrl] = useState(k?.default_url ?? '');
  const [model, setModel] = useState(k?.default_model ?? '');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const pick = (v: string) => {
    setKind(v);
    setName(kinds[v].label.replace(/ \(.*\)$/, ''));
    setUrl(kinds[v].default_url);
    setModel(kinds[v].default_model);
  };
  const submit = async () => {
    setBusy(true);
    try {
      await api.createProvider({ name: name.trim() || k.label, kind, base_url: url || null, model, api_key: key || null, enabled: false });
      toast.success('Provider added', 'Test the connection, then enable it.');
      onDone();
      onClose();
    } catch (e) {
      toast.error('Could not add provider', errMsg(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      title="Add AI provider"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} onClick={submit}>
            Add
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Provider type">
          <Select value={kind} onChange={pick} options={Object.entries(kinds).map(([id, v]) => ({ value: id, label: `${v.label}${v.local ? '' : ' — cloud'}` }))} />
        </Field>
        <Field label="Display name">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Base URL">
          <input className={inputCls} value={url} onChange={(e) => setUrl(e.target.value)} />
        </Field>
        <Field label="Model">
          <input className={inputCls} value={model} placeholder="Pick after testing the connection" onChange={(e) => setModel(e.target.value)} />
        </Field>
        {kind !== 'ollama' && (
          <Field label={`API key${k?.needs_key ? ' (required)' : ' (optional)'}`} hint="Stored encrypted with Windows DPAPI and never sent back to the browser.">
            <input className={inputCls} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
        )}
      </div>
    </Modal>
  );
}

function PrivacyModal({ provider, summary, onClose, onConfirm }: { provider: Provider | null; summary: PrivacySummary | null; onClose: () => void; onConfirm: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      open={!!provider}
      onClose={onClose}
      title={`Privacy review — ${provider?.name ?? ''}`}
      width={560}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            icon={<ShieldCheck className="h-3.5 w-3.5" />}
            onClick={async () => {
              setBusy(true);
              await onConfirm();
              setBusy(false);
              onClose();
            }}
          >
            I understand — enable
          </Button>
        </>
      }
    >
      {!summary ? (
        <LoadingBlock />
      ) : (
        <div className="flex flex-col gap-3 text-xs">
          <div>
            <div className="mb-1 font-semibold text-amber-300">Sent to the provider</div>
            <ul className="list-disc space-y-0.5 pl-4 text-ink-100">
              {summary.sent.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            {provider?.send_frames && <div className="mt-1 text-amber-300">Video frames are enabled for this provider.</div>}
          </div>
          <div>
            <div className="mb-1 font-semibold text-emerald-300">Never sent</div>
            <ul className="list-disc space-y-0.5 pl-4 text-ink-100">
              {summary.never_sent.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-md border border-ink-600 bg-ink-850 p-2.5 text-2xs text-ink-300">
            {summary.notes.map((s) => (
              <div key={s}>• {s}</div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
