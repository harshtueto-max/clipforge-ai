import { create } from 'zustand';
import { api, errMsg } from '../api';
import type { Settings } from '../types';
import { toast } from './toast';

interface SettingsState {
  settings: Settings | null;
  loading: boolean;
  load: () => Promise<void>;
  save: (patch: Partial<Settings>, quiet?: boolean) => Promise<boolean>;
}

export const useSettings = create<SettingsState>((set) => ({
  settings: null,
  loading: false,
  load: async () => {
    set({ loading: true });
    try {
      set({ settings: await api.settings() });
    } catch (e) {
      toast.error('Could not load settings', errMsg(e));
    } finally {
      set({ loading: false });
    }
  },
  save: async (patch, quiet) => {
    try {
      const s = await api.saveSettings(patch);
      set({ settings: s });
      if (!quiet) toast.success('Settings saved');
      return true;
    } catch (e) {
      toast.error('Could not save settings', errMsg(e));
      return false;
    }
  },
}));
