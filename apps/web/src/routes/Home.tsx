// / route — landing page. Hero + 3-minute video pitch + CTA into /chat.

import { useState } from "react";
import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader";
import { InfoTooltip } from "../components/InfoTooltip";

export function Home() {
  const [videoPlaying, setVideoPlaying] = useState(false);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-white">
      <SiteHeader />

      <main className="flex flex-col flex-1 min-h-0 w-full max-w-none px-[8%] py-3">
        <section className="py-4 text-center">
          <h1 className="text-2xl font-semibold text-gray-900 mb-2">
            Health price transparency matters.
          </h1>
          <p className="text-gray-600 m-0">
            Ask about any procedure, hospital, or bill. Grounded in real
            data sourced from{" "}
            <strong className="text-gray-900 font-medium">
              359 hospitals in California
            </strong>
            <InfoTooltip
              width={340}
              ariaLabel="Why 359? How many California hospitals are there?"
              icon={<span className="text-sm leading-none">*</span>}
              triggerClassName="text-blue-900 font-bold align-super px-0.5 hover:text-blue-950"
            >
              <p>
                359 of California's <strong>378</strong> Medicare-certified
                hospitals — the 19 missing are psych, VA, and DoD
                facilities exempt from §180.50.
              </p>
              <p className="mt-2 text-gray-500">
                Next: 6,000+ hospitals nationwide.
              </p>
            </InfoTooltip>
            {" "}— no sign-up, no tracking.
          </p>
        </section>

        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl flex flex-col items-center gap-5 mt-4">
            <div className="w-full aspect-video rounded-lg overflow-hidden shadow-md bg-black">
              {videoPlaying ? (
                <iframe
                  src="https://www.youtube-nocookie.com/embed/g2JJJsArDT8?autoplay=1&rel=0&modestbranding=1&iv_load_policy=3&playsinline=1"
                  title="Health Price Transparency — 3-minute demo"
                  allow="autoplay; encrypted-media; picture-in-picture"
                  allowFullScreen
                  className="w-full h-full border-0"
                />
              ) : (
                <button
                  type="button"
                  onClick={() => setVideoPlaying(true)}
                  aria-label="Play the 3-minute demo"
                  className="group relative block h-full w-full cursor-pointer border-0 bg-transparent p-0"
                >
                  <img
                    src="https://img.youtube.com/vi/g2JJJsArDT8/maxresdefault.jpg"
                    alt="Health Price Transparency — 3-minute demo"
                    className="h-full w-full object-cover"
                  />
                  <span className="absolute inset-0 flex items-center justify-center">
                    <span className="flex h-16 w-16 items-center justify-center rounded-full bg-black/60 group-hover:bg-black/80 transition">
                      <svg
                        aria-hidden="true"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        className="ml-1 h-7 w-7 text-white"
                      >
                        <path d="M8 5v14l11-7z" />
                      </svg>
                    </span>
                  </span>
                </button>
              )}
            </div>
            <Link
              to="/chat"
              className="inline-flex items-center justify-center rounded-full bg-blue-900 px-6 py-2.5 text-base font-medium text-white hover:bg-blue-950 transition no-underline"
            >
              Try it →
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
