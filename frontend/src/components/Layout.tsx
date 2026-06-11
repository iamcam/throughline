// src/components/Layout.tsx
import { NavLink, Outlet } from 'react-router-dom'

export default function Layout() {
    return (
        <div className="min-h-screen">
            <nav className="border-b px-6 py-3 flex items-center gap-6">
                <span className="font-semibold">Podcast Knowledge Engine</span>
                <NavLink
                    to="/feeds"
                    className={({ isActive }) =>
                        isActive ? 'text-primary text-sm' : 'text-sm hover:text-cyan-500 transition-colors'
                    }
                >
                    Feeds
                </NavLink>
                <NavLink
                    to="/chat"
                    className={({ isActive }) =>
                        isActive ? 'text-sm' : 'text-sm hover:text-cyan-500 transition-colors'
                    }
                >
                    Chat
                </NavLink>
            </nav>
            <main className="p-6">
                <Outlet />
            </main>
        </div>
    )
}