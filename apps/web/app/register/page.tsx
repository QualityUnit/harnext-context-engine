import Link from "next/link";

// Registration is invite-only on this instance — accounts are created by an
// admin (see scripts/create-user.sh). This page is intentionally locked.
export default function RegisterPage() {
  return (
    <div className="auth">
      <div className="page-grid" aria-hidden="true" />
      <div className="form-card">
        <div className="fc-brand">
          <span className="fc-emblem-mark">
            <span className="brand-grid" />
          </span>
          <div className="fc-wordmark">
            MeaningGrid<span className="fc-oss">OSS</span>
          </div>
        </div>

        <div className="fc-head">
          <div className="fc-title">Registration is closed</div>
          <div className="fc-sub">
            MeaningGrid is invite-only — an admin provisions accounts. Once yours exists, sign in.
          </div>
        </div>

        <Link className="succ-btn" href="/login">
          Back to sign in
        </Link>

        <div className="selfhost">
          Running your own instance?{" "}
          <a href="https://github.com/yasha-dev1/meaninggrid" target="_blank" rel="noreferrer">
            Self-host →
          </a>
        </div>
      </div>
    </div>
  );
}
