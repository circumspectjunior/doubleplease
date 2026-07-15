const EDGE_SCALE_MAX = 0.3; // bars scale to 30pp edge, matches Section 6's "suspect" ceiling

function formatDate(dateStr) {
  const date = new Date(dateStr + "T00:00:00");
  return date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export default function PickCard({ rank, pick }) {
  const edgePct = pick.edge * 100;
  const barWidth = Math.min(100, (Math.abs(pick.edge) / EDGE_SCALE_MAX) * 100);

  return (
    <li className={`pick ${pick.suspect ? "pick--suspect" : ""}`}>
      <span className="pick__rank mono">{String(rank).padStart(2, "0")}</span>

      <div className="pick__body">
        <div className="pick__meta">
          <span className="pick__league">{pick.league}</span>
          <span className="pick__date">{formatDate(pick.match_date)}</span>
        </div>
        <p className="pick__match">
          {pick.home_team} <span className="pick__vs">vs</span> {pick.away_team}
        </p>
      </div>

      <div className="pick__figures">
        <div className="pick__pick-chip">{pick.pick}</div>
        <div className="pick__figure">
          <span className="pick__figure-label">odds</span>
          <span className="mono">{pick.odds.toFixed(2)}</span>
        </div>
        <div className="pick__figure">
          <span className="pick__figure-label">model</span>
          <span className="mono">{Math.round(pick.model_probability * 100)}%</span>
        </div>
        <div className="pick__edge">
          <div className="pick__edge-bar-track">
            <div className="pick__edge-bar" style={{ width: `${barWidth}%` }} />
          </div>
          <span className="pick__edge-value mono">
            {edgePct > 0 ? "+" : ""}
            {edgePct.toFixed(1)}%
          </span>
        </div>
      </div>
      {pick.suspect && (
        <p className="pick__suspect-note">
          ⚠ Edge over 20pp - more likely a data issue than real value. See review.md.
        </p>
      )}
    </li>
  );
}
