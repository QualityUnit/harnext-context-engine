// Icon set ported from the MeaningGrid design handoff (auth.jsx).
type P = { size?: number };
const s = (n = 16) => ({
  width: n,
  height: n,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const IMail = ({ size }: P) => (
  <svg {...s(size)}>
    <rect x="2" y="4" width="20" height="16" rx="2.5" />
    <path d="m3 6.5 9 6 9-6" />
  </svg>
);
export const ILock = ({ size }: P) => (
  <svg {...s(size)}>
    <rect x="4" y="11" width="16" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </svg>
);
export const IUser = ({ size }: P) => (
  <svg {...s(size)}>
    <circle cx="12" cy="8" r="3.4" />
    <path d="M5 20a7 7 0 0 1 14 0" />
  </svg>
);
export const IEye = ({ size }: P) => (
  <svg {...s(size)}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
    <circle cx="12" cy="12" r="2.6" />
  </svg>
);
export const IEyeOff = ({ size }: P) => (
  <svg {...s(size)}>
    <path d="M3 3l18 18" />
    <path d="M10.6 6.2A9.8 9.8 0 0 1 12 6c6.5 0 10 6 10 6a16 16 0 0 1-3.3 3.9M6.2 7.3A16 16 0 0 0 2 12s3.5 6 10 6a9.6 9.6 0 0 0 4-.85" />
  </svg>
);
export const IGitHub = ({ size }: P) => (
  <svg {...s(size ?? 17)}>
    <line x1="6" y1="3" x2="6" y2="15" />
    <circle cx="18" cy="6" r="3" />
    <circle cx="6" cy="18" r="3" />
    <path d="M18 9a9 9 0 0 1-9 9" />
  </svg>
);
export const IGoogle = ({ size }: P) => (
  <svg {...s(size)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v8M8 12h8" />
  </svg>
);
export const IAlert = ({ size }: P) => (
  <svg {...s(size ?? 13)} strokeWidth={2}>
    <circle cx="12" cy="12" r="9" />
    <line x1="12" y1="8" x2="12" y2="13" />
    <line x1="12" y1="16.5" x2="12" y2="16.5" />
  </svg>
);
export const ICheck = ({ size }: P) => (
  <svg {...s(size ?? 26)} strokeWidth={2.2}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
);
export const IArrow = ({ size }: P) => (
  <svg {...s(size ?? 15)} strokeWidth={2}>
    <line x1="5" y1="12" x2="19" y2="12" />
    <polyline points="12 5 19 12 12 19" />
  </svg>
);
export const IServer = ({ size }: P) => (
  <svg {...s(size ?? 13)}>
    <rect x="3" y="4" width="18" height="7" rx="1.5" />
    <rect x="3" y="13" width="18" height="7" rx="1.5" />
    <line x1="7" y1="7.5" x2="7" y2="7.5" />
    <line x1="7" y1="16.5" x2="7" y2="16.5" />
  </svg>
);
