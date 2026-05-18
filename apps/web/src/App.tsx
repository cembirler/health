// Routes:
//   /            → Home (landing page with brief intro + CTA)
//   /home        → redirect to /
//   /chat        → Chat (new conversation)
//   /chat/:id    → Chat (specific session)
//   /writeup     → Writeup (Kaggle submission writeup + 3-min video)
//   /details     → redirect to /writeup (legacy URL)
//   anything else → redirect to /

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Analytics } from "@vercel/analytics/react";
import { SpeedInsights } from "@vercel/speed-insights/react";
import { Home } from "./routes/Home";
import { Chat } from "./routes/Chat";
import { Writeup } from "./routes/Writeup";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/home" element={<Navigate to="/" replace />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/chat/:sessionId" element={<Chat />} />
        <Route path="/writeup" element={<Writeup />} />
        <Route path="/details" element={<Navigate to="/writeup" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* Tracks SPA route changes. Inert in dev (Vercel filters non-prod
          hosts). No-op until you enable Web Analytics in the Vercel
          dashboard. */}
      <Analytics />
      <SpeedInsights />
    </BrowserRouter>
  );
}

export default App;
