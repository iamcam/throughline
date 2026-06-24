// src/components/Layout.tsx
import { ModeToggle } from "@/components/ThemeModeToggle"
import { NavLink, Outlet } from 'react-router-dom'

export default function Layout() {
  return (
    <div className="flex flex-col h-screen">
      <nav className="border-b px-6 py-3 flex justify-between items-center gap-6 shrink-0">
        <div className="px-6 py-3 flex items-center gap-6 shrink-0">
        <NavLink to="/">
          <span className="font-semibold">Podcast Knowledge Engine</span>
        </NavLink>
        <NavLink
          to="/feeds"
          className={({ isActive }) =>
            isActive ? 'text-primary text-sm' : 'text-sm hover:text-hover transition-colors'
          }
        >
          Feeds
        </NavLink>
        <NavLink
          to="/chat"
          className={({ isActive }) =>
            isActive ? 'text-sm' : 'text-sm hover:text-hover transition-colors'
          }
        >
          Chat
          </NavLink>
        </div>
        <ModeToggle />

      </nav>
      <main className="flex-1 overflow-auto">

        <Outlet />
      </main>
    </div>
  )
  }