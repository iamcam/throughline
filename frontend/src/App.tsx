// src/App.tsx
import Layout from '@/components/Layout'
import EpisodeDetailPage from '@/pages/EpisodeDetailPage'
import EpisodesPage from '@/pages/EpisodesPage'
import FeedsPage from '@/pages/FeedsPage'
import SpeakerNamingPage from '@/pages/SpeakerNamingPage'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

const ChatPage = lazy(() => import('@/pages/ChatPage'))

export default function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route element={<Layout />}>
                    <Route index element={<Navigate to="/feeds" replace />} />
                    <Route path="/feeds" element={<FeedsPage />} />
                    <Route path="/feeds/:feedId/episodes" element={<EpisodesPage />} />
                    <Route path="/episodes/:episodeId" element={<EpisodeDetailPage />} />
                    <Route path="/episodes/:episodeId/speakers" element={<SpeakerNamingPage />} />
                    <Route path="/chat" element={
                        <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading...</div>}>
                            <ChatPage />
                        </Suspense>
                    } />
                </Route>
            </Routes>
        </BrowserRouter>
    )
}