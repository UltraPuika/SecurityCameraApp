import { useTranslation } from "react-i18next";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { CamerasPage } from "./pages/CamerasPage";
import { CameraView } from "./pages/CameraView";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { AccountsPage } from "./pages/admin/AccountsPage";
import { CameraEditor } from "./pages/admin/CameraEditor";
import { CamerasAdminPage } from "./pages/admin/CamerasAdminPage";
import { DiagnosticsPage } from "./pages/admin/DiagnosticsPage";

function Routed() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();

  if (loading) return <p className="splash">{t("app.loading")}</p>;
  if (!user) return <LoginPage />;
  const admin = user.role === "admin";

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<CamerasPage view="all" />} />
        <Route path="favourites" element={<CamerasPage view="favourites" />} />
        <Route path="locations" element={<CamerasPage view="locations" />} />
        <Route path="offline" element={<CamerasPage view="offline" />} />
        <Route path="camera/:id" element={<CameraView />} />
        <Route path="settings" element={<SettingsPage />} />
        {admin && (
          <>
            <Route path="settings/cameras" element={<CamerasAdminPage />} />
            <Route path="settings/cameras/:id" element={<CameraEditor />} />
            <Route path="settings/accounts" element={<AccountsPage />} />
            <Route path="settings/diagnostics" element={<DiagnosticsPage />} />
          </>
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routed />
      </BrowserRouter>
    </AuthProvider>
  );
}
