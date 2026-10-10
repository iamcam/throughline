// src/components/Layout.tsx
import { QueueActivity } from "@/components/QueueActivity";
import { ModeToggle } from "@/components/ThemeModeToggle";
import { useQueuePoller } from "@/hooks/useQueue";
import { NavLink, Outlet, useLocation } from 'react-router-dom';

export default function Layout() {
  const location = useLocation();
  useQueuePoller();
  return (
    <div className="flex flex-col h-screen">
      <nav className="border-b px-4 py-3 flex justify-between items-center shrink-0">
        <div className="py-3 flex items-center gap-6 shrink-0">
          <NavLink to="/">
              <div className="font-logo text-3xl font-black text-primary">throughline</div>
          </NavLink>
        </div>
        <div className="flex gap-3">
          {location.pathname !== "/queue" && <QueueActivity />}
          <ModeToggle />
        </div>
      </nav>

      <main className="flex-1 overflow-auto scrollbar-thin scrollbar-gutter-auto dark:scrollbar-track-card dark:scrollbar-thumb-card-foreground">
        <Outlet />
      </main>
    </div>
  )
  }