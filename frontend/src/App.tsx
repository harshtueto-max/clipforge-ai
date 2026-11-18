import { useEffect } from 'react';
import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Toaster } from './components/Toaster';
import { EditorPage } from './editor/EditorPage';
import { AudioLibraryPage } from './pages/AudioLibrary';
import { ClipLibraryPage } from './pages/ClipLibrary';
import { DashboardPage } from './pages/Dashboard';
import { LiveStudioPage } from './pages/LiveStudio';
import { NewProjectPage } from './pages/NewProject';
import { NotFoundPage } from './pages/NotFound';
import { ProjectPage } from './pages/ProjectPage';
import { ProjectsPage } from './pages/Projects';
import { SettingsPage } from './pages/Settings';
import { useJobs } from './stores/jobs';

export default function App() {
  const start = useJobs((s) => s.start);
  useEffect(() => {
    start();
  }, [start]);
  return (
    <>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/new" element={<NewProjectPage />} />
          <Route path="/live" element={<LiveStudioPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/editor/:clipId" element={<EditorPage />} />
          <Route path="/clips" element={<ClipLibraryPage />} />
          <Route path="/audio" element={<AudioLibraryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
      <Toaster />
    </>
  );
}
