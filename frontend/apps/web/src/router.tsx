import { createBrowserRouter, Navigate, type RouteObject } from 'react-router';
import { RequireAuth } from './app/auth.tsx';
import { AppShell } from './layouts/AppShell.tsx';
import { AuthLayout } from './layouts/AuthLayout.tsx';
import { LoginPage, SignupPage } from './routes/auth/AuthPages.tsx';
import {
  ClipPage,
  DiscoverPage,
  FeedPage,
  NotFoundPage,
  ProfileEditPage,
  ProfilePage,
  SkaterPage,
  TeamPage,
  TeamsPage,
  UploadPage,
} from './routes/screens.tsx';
import { SettingsPage } from './routes/settings/SettingsPage.tsx';

/** Every URL in the app (docs/components/frontend.md, Routes). Exported for tests. */
export const routes: RouteObject[] = [
  {
    element: <AuthLayout />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/signup', element: <SignupPage /> },
    ],
  },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { path: '/', element: <Navigate to="/feed" replace /> },
      { path: '/feed', element: <FeedPage /> },
      { path: '/discover', element: <DiscoverPage /> },
      { path: '/upload', element: <UploadPage /> },
      { path: '/clips/:clipId', element: <ClipPage /> },
      { path: '/profile', element: <ProfilePage /> },
      { path: '/profile/edit', element: <ProfileEditPage /> },
      { path: '/u/:username', element: <SkaterPage /> },
      { path: '/teams', element: <TeamsPage /> },
      { path: '/t/:slug', element: <TeamPage /> },
      { path: '/settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
