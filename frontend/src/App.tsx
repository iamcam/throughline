// src/App.tsx
import Layout from '@/components/Layout'
import ChatPage from '@/pages/ChatPage'
import EpisodeDetailPage from '@/pages/EpisodeDetailPage'
import EpisodesPage from '@/pages/EpisodesPage'
import FeedsPage from '@/pages/FeedsPage'
import SpeakerNamingPage from '@/pages/SpeakerNamingPage'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

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
                    <Route path="/chat" element={<ChatPage />} />
                </Route>
            </Routes>
        </BrowserRouter>
    )
}