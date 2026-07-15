const BASE_URL = "http://localhost:8000";

async function getJSON(path, params = {}) {
  const url = new URL(BASE_URL + path);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status}`);
  }
  return response.json();
}

export const getLeagues = () => getJSON("/api/leagues");
export const getShortlist = (league, top = 20) => getJSON("/api/shortlist", { league, top });
export const getCalibration = (testSeason) => getJSON("/api/calibration", { test_season: testSeason });
export const getStatus = () => getJSON("/api/status");
