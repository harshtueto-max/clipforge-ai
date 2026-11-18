import { Pause, Play } from 'lucide-react';
import { create } from 'zustand';
import { apiUrl } from '../api';
import { IconButton } from './ui';

interface PreviewState {
  playingId: string | null;
  toggle: (id: string, url: string) => void;
  stop: () => void;
}

let audio: HTMLAudioElement | null = null;

export const useAudioPreview = create<PreviewState>((set, get) => ({
  playingId: null,
  toggle: (id, url) => {
    if (!audio) {
      audio = new Audio();
      audio.addEventListener('ended', () => set({ playingId: null }));
      audio.addEventListener('error', () => set({ playingId: null }));
    }
    if (get().playingId === id) {
      audio.pause();
      set({ playingId: null });
      return;
    }
    audio.pause();
    audio.src = apiUrl(url);
    audio.currentTime = 0;
    void audio.play().catch(() => set({ playingId: null }));
    set({ playingId: id });
  },
  stop: () => {
    audio?.pause();
    set({ playingId: null });
  },
}));

export function PreviewButton({ id, url }: { id: string; url: string }) {
  const { playingId, toggle } = useAudioPreview();
  const on = playingId === id;
  return (
    <IconButton title={on ? 'Stop preview' : 'Preview'} active={on} onClick={(e) => (e.stopPropagation(), toggle(id, url))}>
      {on ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
    </IconButton>
  );
}
