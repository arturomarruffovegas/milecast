export const riskLevels = ['Low', 'Moderate', 'High', 'Severe', 'No Travel']
export const routeColors = ['#6246d9', '#208b8b', '#63769a']
export const riskColors = ['#3e9e6d', '#e5b343', '#ed873f', '#da535a', '#773d72']

export function journeyTime(minutes) {
  const total = Math.round(minutes)
  if (total < 60) return total + ' min'
  return Math.floor(total / 60) + 'h ' + String(total % 60).padStart(2, '0') + 'm'
}

export function displayTime(iso, withDate = false) {
  const options = { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }
  if (withDate) Object.assign(options, { month: 'short', day: 'numeric' })
  return new Date(iso).toLocaleString('en-US', options)
}

export function placeName(place) {
  return /^[-+\d.]+,\s*[-+\d.]+$/.test(place.name) ? place.name : place.name.split(',')[0]
}
