// Icon set ported from the Harnext design handoff (auth.jsx).
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
  <svg width={size ?? 17} height={size ?? 17} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
  </svg>
);
export const IGoogle = ({ size }: P) => (
  <svg width={size ?? 16} height={size ?? 16} viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#4285F4" d="M23.52 12.273c0-.851-.076-1.67-.218-2.455H12v4.642h6.458a5.52 5.52 0 0 1-2.394 3.622v3.013h3.878c2.27-2.09 3.578-5.17 3.578-8.822z" />
    <path fill="#34A853" d="M12 24c3.24 0 5.956-1.075 7.942-2.905l-3.878-3.013c-1.075.72-2.45 1.146-4.064 1.146-3.125 0-5.77-2.11-6.714-4.945H1.276v3.11A11.997 11.997 0 0 0 12 24z" />
    <path fill="#FBBC05" d="M5.286 14.283A7.21 7.21 0 0 1 4.91 12c0-.792.136-1.562.376-2.283v-3.11H1.276A11.997 11.997 0 0 0 0 12c0 1.936.464 3.768 1.276 5.393l4.01-3.11z" />
    <path fill="#EA4335" d="M12 4.773c1.762 0 3.345.605 4.59 1.793l3.44-3.44C17.951 1.186 15.235 0 12 0A11.997 11.997 0 0 0 1.276 6.607l4.01 3.11C6.23 6.882 8.875 4.773 12 4.773z" />
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
