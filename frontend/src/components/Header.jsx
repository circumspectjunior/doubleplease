function formatTimestamp(iso) {
  if (!iso) return "never";
  const date = new Date(iso.replace(" ", "T") + (iso.includes("Z") ? "" : "Z"));
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function Header({ status }) {
  return (
    <header className="header">
      <div className="header__row">
        <div>
          <p className="header__eyebrow">Weekly double-chance shortlist</p>
          <h1 className="header__title">DOUBLE PLEASE</h1>
        </div>
        {status && (
          <dl className="header__stats">
            <div>
              <dt>Tracked matches</dt>
              <dd className="mono">{status.matches.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Upcoming fixtures</dt>
              <dd className="mono">{status.scheduled_matches}</dd>
            </div>
            <div>
              <dt>Odds last pulled</dt>
              <dd className="mono">{formatTimestamp(status.last_odds_fetched_at)}</dd>
            </div>
          </dl>
        )}
      </div>
    </header>
  );
}
