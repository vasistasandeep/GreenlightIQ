# CineROI AI — Frontend

Next.js (App Router) + TypeScript executive decision-support UI, styled with
Tailwind and Shadcn UI, charts via Recharts.

```
frontend/
├── app/
│   ├── dashboard/       # Executive Command Dashboard (R14, task 19)
│   ├── titles/[id]/     # Deep-Dive Title Evaluation (R15, task 20)
│   ├── backtest/        # Backtesting & Calibration Studio (R16, task 21)
│   ├── layout.tsx
│   ├── page.tsx         # redirects to /dashboard
│   └── globals.css
├── components/          # Shadcn UI + Recharts components (tasks 19-21)
├── lib/                 # typed API client, shared types, utils
├── package.json
├── tailwind.config.ts
└── tsconfig.json
```

## Setup

```bash
npm install
cp .env.example .env.local
```

## Run

```bash
npm run dev        # http://localhost:3000
npm run build
npm run typecheck
```
