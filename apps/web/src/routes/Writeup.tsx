// /writeup — Kaggle Proof-of-Work writeup. Paper/blog style: title +
// subtitle, abstract, architecture, how Gemma 4 is used, engineering
// decisions, challenges, data provenance. Stays under the 1,500-word
// writeup cap. The live agent at the root of this site is the practical
// demonstration; this page is the technical verification of that demo.

import {
  ArrowRight,
  Bot,
  Building2,
  Database,
  FileText,
  Globe,
  Monitor,
  Server,
} from "lucide-react";

// Inline GitHub mark — lucide-react in our pinned version doesn't export
// a `Github` icon (brand icons were removed).
function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className={className}
    >
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.55v-1.93c-3.2.7-3.87-1.54-3.87-1.54-.52-1.33-1.27-1.69-1.27-1.69-1.04-.71.08-.69.08-.69 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.69 1.25 3.34.95.1-.74.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .97-.31 3.18 1.18a11.05 11.05 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.58.23 2.75.11 3.04.74.81 1.18 1.84 1.18 3.1 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.13v3.16c0 .31.21.67.8.55C20.21 21.38 23.5 17.07 23.5 12 23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}
import { SiteHeader } from "../components/SiteHeader";
import detailsHero from "../assets/details-hero.png";

// Generic icon-card link used for "Live demo" / "Source on GitHub" / etc.
// Icon component just needs to accept `className` — works for both
// lucide-react icons and the inline GitHubIcon below.
function LinkCard({
  href,
  icon: Icon,
  title,
  subtitle,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  subtitle: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener"
      className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 text-gray-800 hover:border-gray-300 hover:bg-gray-50 transition no-underline min-w-0"
    >
      <Icon className="h-5 w-5 text-gray-900 flex-shrink-0" />
      <div className="flex flex-col leading-tight min-w-0">
        <span className="text-sm font-medium text-gray-900 truncate">
          {title}
        </span>
        <span className="text-xs text-gray-500 truncate">{subtitle}</span>
      </div>
    </a>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-16">
      <h2 className="text-2xl font-bold text-gray-900 tracking-tight leading-snug mb-8">
        {title}
      </h2>
      <div className="text-[15px] leading-relaxed text-gray-700 space-y-4">
        {children}
      </div>
    </section>
  );
}

function StatCard({
  value,
  label,
  sublabel,
}: {
  value: string;
  label: string;
  sublabel?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-gradient-to-b from-blue-50/60 to-white px-4 py-5 text-center">
      <div className="text-2xl font-semibold text-blue-900 tabular-nums">
        {value}
      </div>
      <div className="text-sm text-gray-800 mt-0.5">{label}</div>
      {sublabel && (
        <div className="text-xs text-gray-500 mt-0.5">{sublabel}</div>
      )}
    </div>
  );
}

// One node in the architecture diagram — icon + 2-line label.
function PipelineNode({
  icon: Icon,
  title,
  subtitle,
}: {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex flex-col items-center text-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-4 min-w-[120px]">
      <div className="grid h-9 w-9 place-items-center rounded-lg bg-blue-900 text-white">
        <Icon className="h-4 w-4" strokeWidth={2.25} />
      </div>
      <div className="text-sm font-medium text-gray-900 leading-tight">
        {title}
      </div>
      <div className="text-[11px] text-gray-500 leading-tight">{subtitle}</div>
    </div>
  );
}

function PipelineArrow() {
  return (
    <div className="hidden md:flex items-center text-gray-300 shrink-0">
      <ArrowRight className="h-5 w-5" />
    </div>
  );
}

export function Writeup() {
  return (
    <div className="flex flex-col min-h-screen bg-white">
      <SiteHeader />

      <main className="mx-auto w-full max-w-3xl px-6 pb-24 pt-10">
        {/* Title + subtitle satisfies Kaggle's "Title, subtitle, detailed
            analysis" writeup checklist. */}
        <header>
          <h1 className="text-3xl font-semibold text-gray-900 tracking-tight leading-tight">
            Health Price Transparency
          </h1>
          <p className="mt-2 text-lg text-gray-700 leading-snug">
            A Gemma&nbsp;4 agent that turns the hidden CMS hospital-pricing
            dataset into grounded, sourced, sub-3-second answers for
            ordinary patients.
          </p>
          <p className="mt-4 text-[15px] leading-relaxed text-gray-600">
            Submission for the{" "}
            <strong className="text-gray-900 font-semibold">
              Gemma&nbsp;4 Good Hackathon
            </strong>
            , Health&nbsp;&amp;&nbsp;Sciences track.
          </p>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <LinkCard
              href="https://www.healthpricetransparency.com/"
              icon={Globe}
              title="healthpricetransparency.com"
              subtitle="Live demo"
            />
            <LinkCard
              href="https://github.com/cembirler/health"
              icon={GitHubIcon}
              title="cembirler/health"
              subtitle="Source on GitHub"
            />
          </div>
        </header>

        {/* Quick stats panel — concrete proof points right under the lede
            so the page leads with numbers instead of three pages of prose. */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-10">
          <StatCard
            value="359"
            label="hospitals"
            sublabel="California, today"
          />
          <StatCard
            value="15.3M"
            label="priced items"
            sublabel="per-hospital × code"
          />
          <StatCard
            value="136M"
            label="payer rates"
            sublabel="negotiated, by plan"
          />
          <StatCard
            value="6,000+"
            label="hospital target"
            sublabel="full US, same pipeline"
          />
        </div>

        {/* Hero shot — what the live agent looks like. (The demo video
            lives in the Kaggle Media Gallery, not embedded here, so this
            page reads as a clean technical writeup.) */}
        <div className="mt-10">
          <img
            src={detailsHero}
            alt="Health Price Transparency — the agent answering a price-comparison question across hospitals"
            className="w-full rounded-xl border border-gray-200 shadow-sm"
          />
        </div>

        <Section title="Problem">
          <p>
            Since 2021, U.S. hospitals are legally required to publish
            complete price lists — gross charges, cash prices, and every
            negotiated payer rate — as machine-readable files (MRFs).
            Compliance is over 80%, but the files are 100MB+ CSVs in 20+
            schema dialects hidden three clicks deep on hospital sites.
            The data the law made public is, for an ordinary patient,
            still invisible.
          </p>
          <p>
            This project closes that gap end-to-end: a Python ingest
            pipeline that normalizes the long tail of MRF dialects into a
            queryable MySQL corpus, a FastAPI tool surface exposing six
            grounded query primitives, and a Gemma&nbsp;4 agent that
            answers natural-language patient questions strictly from those
            tools — never from parametric memory. 333 California MRFs
            (~15.3M priced items, ~136M payer rates) are loaded today;
            the same pipeline scales to the full ~6,000-hospital U.S.
            universe with zero architectural change.
          </p>
        </Section>

        <Section title="How Gemma 4 powers the agent">
          <p>
            The default model is{" "}
            <code className="font-mono text-gray-900">
              gemma-4-26b-a4b-it
            </code>{" "}
            — the mixture-of-experts variant of Gemma&nbsp;4 (~26B
            parameters total, ~4B activated per token). It's served
            through Google AI Studio's hosted{" "}
            <code className="font-mono text-gray-900">generateContent</code>{" "}
            endpoint and called from{" "}
            <code className="font-mono text-gray-900">
              apps/api/agent/agent.py
            </code>
            . The agent surface uses Gemma in four concrete ways:
          </p>
          <ol className="list-decimal space-y-3 pl-5">
            <li>
              <strong className="text-gray-900 font-semibold">
                Native function calling.
              </strong>{" "}
              Tool schemas (
              <code className="font-mono text-gray-900">find_procedure</code>
              ,{" "}
              <code className="font-mono text-gray-900">find_prices</code>,{" "}
              <code className="font-mono text-gray-900">
                price_distribution
              </code>
              ,{" "}
              <code className="font-mono text-gray-900">
                compare_hospitals
              </code>
              ,{" "}
              <code className="font-mono text-gray-900">find_hospital</code>
              ,{" "}
              <code className="font-mono text-gray-900">get_mrf</code>) are
              sent as Gemini-compatible{" "}
              <code className="font-mono text-gray-900">
                function_declarations
              </code>{" "}
              with strict JSON Schema arguments. The model picks the right
              tool, fills the args from natural language, and the loop
              dispatches them sequentially — no hand-written intent
              classifier, no LangChain. The whole orchestrator is{" "}
              <strong className="text-gray-900 font-semibold">
                ~150 lines
              </strong>{" "}
              of Python.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Thought-token streaming.
              </strong>{" "}
              Gemma&nbsp;4 emits{" "}
              <code className="font-mono text-gray-900">thoughtSummary</code>{" "}
              parts before each tool call. The agent persists those to{" "}
              <code className="font-mono text-gray-900">chat_requests</code>
              ; the UI renders them as a soft{" "}
              <em>thinking</em> bubble above the tool block so users see
              the model's reasoning live. Failures heal gracefully — if a
              reply tag is unclosed, the agent re-tries up to{" "}
              <code className="font-mono text-gray-900">max_iterations</code>
              .
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Agentic retrieval discipline.
              </strong>{" "}
              The system prompt forbids parametric pricing answers; every
              dollar figure in a reply must come from a tool observation,
              and the UI cross-links each number back to its source MRF
              row. This is enforced at the data layer too — the API tools
              never invent prices, only project columns from the corpus.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Offline corpus enrichment.
              </strong>{" "}
              Hospital MRF descriptions are written in CPT shorthand
              ("mri jnt of lwr extre w/o dye") that no patient types.
              Before serving traffic, Gemma generates plain-English
              summaries per code into the{" "}
              <code className="font-mono text-gray-900">
                codes.gemma_description
              </code>{" "}
              column, joined into{" "}
              <code className="font-mono text-gray-900">find_procedure</code>
              's LIKE-match alongside the official descriptors and 108
              hand-curated consumer aliases. This is what makes "knee mri"
              actually resolve to CPT&nbsp;73721 even though no hospital
              writes the word "knee" in its description.
            </li>
          </ol>
          <p>
            <strong className="text-gray-900 font-semibold">
              Why Gemma 4 specifically?
            </strong>{" "}
            Three reasons. (1) The MoE A4B variant runs at roughly the cost
            of a 4B-active model while inheriting 26B-class function-calling
            quality — material when an agent loop fires 4–8 tool round-trips
            per turn. (2) Open weights mean the entire stack stays
            deployable on a hospital's own GPU later — important for
            HIPAA-sensitive extensions like itemized-bill auditing. (3)
            Gemma's thought-token surfacing is what makes the trace UI
            honest; without it, the agent would look like a black box even
            though every step is grounded.
          </p>
        </Section>

        <Section title="Architecture">
          {/* Visual data flow — same content as the bullet list below,
              but a glance-able pipeline for readers who scan first.
              Wraps to two rows on narrow viewports (arrows hide via
              md:hidden inside PipelineArrow). */}
          <div className="flex flex-wrap items-stretch justify-center gap-3 md:gap-2 mb-4">
            <PipelineNode
              icon={Building2}
              title="Hospitals"
              subtitle="publish MRFs"
            />
            <PipelineArrow />
            <PipelineNode
              icon={FileText}
              title="Ingest"
              subtitle="parse + normalize"
            />
            <PipelineArrow />
            <PipelineNode
              icon={Database}
              title="MySQL"
              subtitle="15.3M items"
            />
            <PipelineArrow />
            <PipelineNode
              icon={Server}
              title="API"
              subtitle="/agent/tools/*"
            />
            <PipelineArrow />
            <PipelineNode
              icon={Bot}
              title="Gemma 4"
              subtitle="function calling"
            />
            <PipelineArrow />
            <PipelineNode
              icon={Monitor}
              title="Chat UI"
              subtitle="Vite + React"
            />
          </div>

          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="text-gray-900 font-semibold">
                Ingest pipeline
              </strong>{" "}
              (Python). Discovers each hospital's MRF via{" "}
              <code className="font-mono text-gray-900">cms-hpt.txt</code>{" "}
              at the domain root, normalizes ~20 publisher dialects (CSV
              tall+wide and JSON, CMS v2/v3/CY2026), dedupes by SHA-256,
              and bulk-loads into MySQL — 15.3M priced items, 136M payer
              rates. Discovery index in the repo at{" "}
              <a
                href="https://github.com/cembirler/health/blob/main/data/mrf_index.csv"
                target="_blank"
                rel="noreferrer"
                className="font-mono text-blue-900 underline hover:text-blue-950"
              >
                data/mrf_index.csv
              </a>
              .
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">API</strong>{" "}
              (FastAPI). Stateless tool endpoints under{" "}
              <code className="font-mono text-gray-900">
                /api/agent/tools/*
              </code>
              . Each tool returns a strict JSON envelope and cites its
              source MRFs.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Agent loop
              </strong>{" "}
              (Python). Reads the user turn, dispatches function calls to
              the API, and persists every round-trip server-side so the
              UI can render tool-by-tool progress in real time. The
              background task is the source of truth — it survives tab
              close and connection drops, so the user can come back to
              an answer that finished without them.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Frontend
              </strong>{" "}
              (Vite + React). One conversation surface. Every turn shows the
              tools that were called, the exact inputs, the exact outputs,
              and a "verify on hospital site" link back to the original MRF.
            </li>
          </ul>
        </Section>

        <Section title="Engineering challenges & decisions">
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="text-gray-900 font-semibold">
                Schema chaos.
              </strong>{" "}
              Publishers ship pipe-delimited tall CSVs, wide CSVs with one
              column per (payer, plan) combo, nested JSONs, "by location"
              splits where one MRF covers N hospitals, gzipped files with{" "}
              <code className="font-mono text-gray-900">.csv</code>{" "}
              extensions, and legacy v1/v2 formats — all within the
              nominal CMS template. The parser handles each dialect,
              keeps every code type (CPT, HCPCS, MS-DRG, NDC, and
              hospital-internal CDM/RC/LOCAL), splits multi-location rows
              by row-1 pipe fields, dedupes identical bytes across URLs
              by SHA-256, and quarantines structurally-broken files for
              manual review.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Code disambiguation.
              </strong>{" "}
              "Knee MRI" maps to dozens of overlapping codes per hospital
              and zero hospital descriptions contain the word "knee". The
              fix was a layered LIKE search across four columns:
              official CPT descriptor (where licensed), the modal
              hospital description, Gemma's plain-English summary, and a
              hand-curated{" "}
              <code className="font-mono text-gray-900">keywords</code>{" "}
              column with 108 consumer aliases. Function-calling splits
              this into{" "}
              <code className="font-mono text-gray-900">find_procedure</code>{" "}
              (resolve to candidate codes) then{" "}
              <code className="font-mono text-gray-900">
                compare_hospitals
              </code>{" "}
              (price across facilities) instead of one mega-prompt.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Trust by construction.
              </strong>{" "}
              The agent's reply is not the source of truth — the tool
              trace is. Every assistant turn in the UI is one click away
              from the JSON the model saw, and that JSON is one click
              away from the hospital's raw MRF URL with a publish-date
              stamp. There is no re-ranking, no price synthesis, no
              hidden state.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Production tradeoffs.
              </strong>{" "}
              FastAPI + MySQL 8 + SQLAlchemy over a managed Cloud SQL
              instance, behind a stateless Cloud Run service auto-deployed
              on push-to-main. MySQL chosen over Postgres for ease of
              bulk-loading the 136M-row{" "}
              <code className="font-mono text-gray-900">
                hospital_payer_rates
              </code>{" "}
              table with{" "}
              <code className="font-mono text-gray-900">
                LOAD DATA LOCAL INFILE
              </code>
              ; Cloud Run over GKE because the API has zero state of its
              own (session storage is in the DB). Vercel handles the
              SPA + edge rewrite to the Cloud Run origin so{" "}
              <code className="font-mono text-gray-900">/api/*</code>{" "}
              calls stay same-origin and CORS-free.
            </li>
          </ul>
        </Section>

        <Section title="Data sources & verification">
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="text-gray-900 font-semibold">
                Hospital seed
              </strong>{" "}
              — CCN-keyed registry of ~6,100 Medicare-certified US
              hospitals, assembled from the public CMS Provider-of-Services
              file, the CMS HPT Enforcement dataset, and the crowdsourced{" "}
              <a
                href="https://github.com/dolthub/hospital-price-transparency"
                target="_blank"
                rel="noreferrer"
                className="font-mono text-blue-900 underline hover:text-blue-950"
              >
                dolthub/hospital-price-transparency
              </a>{" "}
              registry. Gives the discovery agent its starting list of
              hospital names + websites.
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                MRF discovery agent
              </strong>{" "}
              — Python crawler I built for this project. For every seeded
              hospital it fetches{" "}
              <code className="font-mono text-gray-900">cms-hpt.txt</code>{" "}
              at the domain root (the manifest every hospital is required
              to publish under 45&nbsp;CFR&nbsp;§180.50) and parses out
              each MRF URL. For the ~30–50% of hospitals that don't
              comply, it falls back through several tiers: system-domain
              crawls (HCA, Kaiser, Sutter, CommonSpirit publish one txt
              file covering hundreds of facilities), Azure Blob container
              listings, aggregator directories like Hyve, JSON↔CSV
              twin-URL probes, a Wikidata-derived domain crosswalk,
              Playwright for JS-rendered pricing pages, and a
              web-search fallback. Output is the discovery index linked
              above. Built against the official CMS data dictionaries and
              templates at{" "}
              <a
                href="https://github.com/CMSgov/hospital-price-transparency"
                target="_blank"
                rel="noreferrer"
                className="font-mono text-blue-900 underline hover:text-blue-950"
              >
                github.com/CMSgov/hospital-price-transparency
              </a>
              .
            </li>
            <li>
              <strong className="text-gray-900 font-semibold">
                Code reference
              </strong>{" "}
              — CMS HCPCS (public domain) + publisher CDM descriptions +
              Gemma-generated plain-English summaries + 108 hand-curated
              consumer aliases. CPT descriptors are deliberately not
              redistributed (AMA-licensed); the agent paraphrases rather
              than copies.
            </li>
          </ul>
        </Section>

        <Section title="Feedback">
          <p>
            Every weird edge case the agent gets wrong is something I
            want to know about. If a query felt off, a hospital you care
            about is missing, or a price doesn't match what you were
            billed — email{" "}
            <a
              href="mailto:cembirler@gmail.com"
              className="text-blue-900 hover:text-blue-950 underline"
            >
              cembirler@gmail.com
            </a>
            . I read every message.
          </p>
        </Section>
      </main>
    </div>
  );
}
