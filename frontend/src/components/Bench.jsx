export default function Bench({ picks }) {
  if (picks.length === 0) return null;

  return (
    <section className="bench">
      <div className="bench__heading">
        <h2 className="bench__title">The bench</h2>
        <p className="bench__subtitle">
          {picks.length} {picks.length === 1 ? "fixture" : "fixtures"} held back - one team has
          too few (or zero) games in the training data to trust the model's read on it. Real
          example: Hull City vs Manchester United showed a 37% "edge" that was really just the
          model assuming an unfamiliar team plays like a league-average side.
        </p>
      </div>

      <ul className="bench__list">
        {picks.map((pick) => (
          <li key={`${pick.match_date}-${pick.home_team}-${pick.away_team}`} className="bench__item">
            <span className="bench__league">{pick.league}</span>
            <span className="bench__match">
              {pick.home_team} vs {pick.away_team}
            </span>
            <span className="bench__would-be mono">
              would-be {pick.pick}, {pick.edge > 0 ? "+" : ""}
              {(pick.edge * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
