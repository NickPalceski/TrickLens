import { createBrowserRouter, Navigate, type RouteObject } from 'react-router';
import { RequireAuth, useAuth } from './app/auth.tsx';
import { AppShell } from './layouts/AppShell.tsx';
import { AuthLayout } from './layouts/AuthLayout.tsx';
import { LoginPage, SignupPage } from './routes/auth/AuthPages.tsx';
import { ClipPage } from './routes/clips/ClipPage.tsx';
import { DiscoverPage } from './routes/discover/DiscoverPage.tsx';
import { FeedPage } from './routes/feed/FeedPage.tsx';
import { BugReportPage } from './routes/help/BugReportPage.tsx';
import { NotFoundPage } from './routes/NotFoundPage.tsx';
import { ProfileEditPage, ProfilePage, SkaterPage } from './routes/profile/ProfilePages.tsx';
import { SettingsPage } from './routes/settings/SettingsPage.tsx';
import { CreateTeamPage } from './routes/teams/CreateTeamPage.tsx';
import { TeamPage } from './routes/teams/TeamPage.tsx';
import { TeamSettingsPage } from './routes/teams/TeamSettingsPage.tsx';
import { TeamsPage } from './routes/teams/TeamsPage.tsx';
import { ClipFlowPage } from './routes/upload/ClipFlowPage.tsx';
import { UploadPage } from './routes/upload/UploadPage.tsx';

/** The app frame when signed in, the plain one when not: for pages anyone can use (a login bug). */
function AnyoneLayout() {
  const { session } = useAuth();
  return session ? <AppShell /> : <AuthLayout />;
}

/** Every URL in the app (docs/components/frontend.md, Routes). Exported for tests. */
export const routes: RouteObject[] = [
  {
    element: <AnyoneLayout />,
    children: [{ path: '/report-bug', element: <BugReportPage /> }],
  },
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
      { path: '/upload/:clipId', element: <ClipFlowPage /> },
      { path: '/clips/:clipId', element: <ClipPage /> },
      { path: '/profile', element: <ProfilePage /> },
      { path: '/profile/edit', element: <ProfileEditPage /> },
      { path: '/u/:username', element: <SkaterPage /> },
      { path: '/teams', element: <TeamsPage /> },
      { path: '/teams/new', element: <CreateTeamPage /> },
      { path: '/t/:slug', element: <TeamPage /> },
      { path: '/t/:slug/settings', element: <TeamSettingsPage /> },
      { path: '/settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
