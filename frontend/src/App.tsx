// src/App.tsx
import { ErrorBoundary } from '@/components/ErrorBoundary'
import Layout from '@/components/Layout'
import EpisodeDetailPage from '@/pages/EpisodeDetailPage'
import EpisodesPage from '@/pages/EpisodesPage'
import FeedsPage from '@/pages/FeedsPage'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from './components/theme-provider/ThemeProvider'

const ChatPage = lazy(() => import('@/pages/ChatPage'))

export default function App() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="podkb-ui-theme">
      <BrowserRouter>
        <ErrorBoundary>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Navigate to="/feeds" replace />} />
              <Route path="/feeds" element={<FeedsPage />} />
              <Route path="/feeds/:feedId/episodes" element={<EpisodesPage />} />
              <Route path="/episodes/:episodeId" element={<EpisodeDetailPage />} />
              <Route path="/chat" element={
                <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading...</div>}>
                  <ChatPage />
                </Suspense>
              } />
            </Route>
          </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </ThemeProvider>
  )
}