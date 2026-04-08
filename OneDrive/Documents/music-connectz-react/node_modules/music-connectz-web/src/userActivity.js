// userActivity.js
// Tracks user activity by day and hour in localStorage

export function logUserActivity() {
  const now = new Date();
  const day = now.getDay(); // 0=Sun, 1=Mon, ...
  const hour = now.getHours();
  const key = `activity_${day}_${hour}`;
  const count = Number(localStorage.getItem(key) || 0) + 1;
  localStorage.setItem(key, count);
}

export function getMostActivePeriod() {
  let max = 0, bestDay = 0, bestHour = 0;
  for (let day = 0; day < 7; ++day) {
    for (let hour = 0; hour < 24; ++hour) {
      const count = Number(localStorage.getItem(`activity_${day}_${hour}`) || 0);
      if (count > max) {
        max = count;
        bestDay = day;
        bestHour = hour;
      }
    }
  }
  return { day: bestDay, hour: bestHour };
}
