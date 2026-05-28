import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Bot,
  Brain,
  Database,
  FileText,
  Home,
  Images,
  Link as LinkIcon,
  LogOut,
  Megaphone,
  MessageSquareText,
  Settings,
  Sparkles,
  Tags,
  ShieldCheck,
  Users,
  Gauge
} from "lucide-react";

import { Button } from "./ui";
import { useAuthStore } from "../shared/authStore";

const links = [
  { to: "/admin/dashboard", label: "Dashboard", icon: Home },
  { to: "/admin/crm", label: "CRM", icon: Users },
  { to: "/admin/links", label: "Ссылки", icon: LinkIcon },
  { to: "/admin/audiences", label: "Базы", icon: Database },
  { to: "/admin/leads", label: "Лиды", icon: Users },
  { to: "/admin/analysis", label: "Анализы", icon: Images },
  { to: "/admin/ai-performance", label: "AI latency", icon: Gauge },
  { to: "/admin/reports", label: "Отчеты", icon: FileText },
  { to: "/admin/knowledge", label: "База знаний", icon: Brain },
  { to: "/admin/prompts", label: "Промпты", icon: MessageSquareText },
  { to: "/admin/broadcasts", label: "Рассылки", icon: Megaphone },
  { to: "/admin/campaigns", label: "UTM", icon: Tags },
  { to: "/admin/settings", label: "Настройки", icon: Settings },
  { to: "/admin/managers", label: "Менеджеры", icon: ShieldCheck }
];

export function Layout() {
  const logout = useAuthStore((state) => state.logout);
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-milk text-ink">
      <aside className="fixed inset-y-0 left-0 hidden w-72 border-r border-pearl bg-white/75 p-5 backdrop-blur lg:block">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-card bg-rose text-white">
            <Sparkles size={21} />
          </div>
          <div>
            <p className="font-bold">Bella Vladi</p>
            <p className="text-xs text-clay">Face Protocol Admin</p>
          </div>
        </div>
        <nav className="mt-8 space-y-1">
          {links.map((link) => {
            const Icon = link.icon;
            return (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `flex h-11 items-center gap-3 rounded-card px-3 text-sm font-semibold transition ${
                    isActive ? "bg-pearl text-ink" : "text-clay hover:bg-milk"
                  }`
                }
              >
                <Icon size={18} />
                {link.label}
              </NavLink>
            );
          })}
        </nav>
      </aside>
      <main className="lg:pl-72">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-pearl bg-milk/88 px-5 backdrop-blur">
          <div className="flex items-center gap-2 text-sm font-semibold text-clay">
            <Bot size={18} />
            Production-ready MVP
          </div>
          <Button
            variant="ghost"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            <LogOut size={17} />
            Выйти
          </Button>
        </header>
        <div className="mx-auto max-w-7xl p-5 lg:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export function MiniChartIcon() {
  return <BarChart3 size={20} />;
}
