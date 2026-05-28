import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "../components/Layout";
import { Analysis } from "../pages/Analysis";
import { AnalysisDetail } from "../pages/AnalysisDetail";
import { AiPerformance } from "../pages/AiPerformance";
import { Admins } from "../pages/Admins";
import { Audiences } from "../pages/Audiences";
import { Broadcasts } from "../pages/Broadcasts";
import { Campaigns } from "../pages/Campaigns";
import { CRM } from "../pages/CRM";
import { CrmLeadDetail } from "../pages/CrmLeadDetail";
import { Dashboard } from "../pages/Dashboard";
import { KnowledgeBase } from "../pages/KnowledgeBase";
import { LeadDetail } from "../pages/LeadDetail";
import { Leads } from "../pages/Leads";
import { Links } from "../pages/Links";
import { Login } from "../pages/Login";
import { PromptTemplates } from "../pages/PromptTemplates";
import { PublicReport } from "../pages/PublicReport";
import { Reports } from "../pages/Reports";
import { Settings } from "../pages/Settings";
import { useAuthStore } from "../shared/authStore";

function PrivateRoute() {
  const token = useAuthStore((state) => state.token);
  if (!token) return <Navigate to="/login" replace />;
  return <Layout />;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/admin/dashboard" replace />} />
      <Route path="/login" element={<Login />} />
      <Route path="/report/:publicToken" element={<PublicReport />} />
      <Route path="/admin" element={<PrivateRoute />}>
        <Route index element={<Navigate to="/admin/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="crm" element={<CRM />} />
        <Route path="crm/:id" element={<CrmLeadDetail />} />
        <Route path="links" element={<Links />} />
        <Route path="bases" element={<Audiences />} />
        <Route path="audiences" element={<Audiences />} />
        <Route path="leads" element={<Leads />} />
        <Route path="leads/:id" element={<LeadDetail />} />
        <Route path="analysis" element={<Analysis />} />
        <Route path="analysis/:id" element={<AnalysisDetail />} />
        <Route path="ai-performance" element={<AiPerformance />} />
        <Route path="reports" element={<Reports />} />
        <Route path="knowledge" element={<KnowledgeBase />} />
        <Route path="prompts" element={<PromptTemplates />} />
        <Route path="broadcasts" element={<Broadcasts />} />
        <Route path="campaigns" element={<Campaigns />} />
        <Route path="settings" element={<Settings />} />
        <Route path="admins" element={<Admins />} />
        <Route path="managers" element={<Admins />} />
      </Route>
    </Routes>
  );
}
