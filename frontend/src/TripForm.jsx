import React from 'react'
import { ArrowRight, ArrowUpDown, CalendarDays, Clock3, LoaderCircle, Navigation2, Package, SlidersHorizontal } from 'lucide-react'
import AddressField from './AddressField'
import { riskLevels, riskColors } from './format'

function nextDeparture() {
  const local = new Date()
  local.setHours(local.getHours() + 1, 0, 0, 0)
  const pad = n => String(n).padStart(2, '0')
  return {
    date: [local.getFullYear(), pad(local.getMonth() + 1), pad(local.getDate())].join('-'),
    time: pad(local.getHours()) + ':00',
  }
}

export function initialTrip() {
  return { origin: 'Chicago, IL', destination: 'Madison, WI', ...nextDeparture(), weight: '32000', intervalMiles: 25 }
}

export default function TripForm({ trip, change, submit, busy, openGuide, error }) {
  const zoneDate = trip.date ? new Date(trip.date + 'T12:00') : new Date()
  const zone = new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' }).formatToParts(zoneDate).find(p => p.type === 'timeZoneName')?.value
  const set = (key, value) => change(prev => ({ ...prev, [key]: value }))
  return <aside className="sidebar">
    <div className="side-heading"><div className="section-icon"><SlidersHorizontal size={19}/></div><h1>Trip planner</h1></div>
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <div className="locations">
          <label htmlFor="origin">Origin</label>
          <AddressField id="origin" value={trip.origin} onChange={value => set('origin', value)}/>
          <div className="destination-label"><label htmlFor="destination">Destination</label><button type="button" className="swap" title="Swap origin and destination" aria-label="Swap origin and destination" onClick={() => change(prev => ({...prev,origin:prev.destination,destination:prev.origin}))}><ArrowUpDown size={13}/> Swap</button></div>
          <AddressField id="destination" value={trip.destination} onChange={value => set('destination', value)}/>
          <p className="place-hint">Search by street address, city, or ZIP code.</p>
        </div>
        <div className="form-block">
          <div className="field-label">Departure <span className="zone">{zone || 'Local time'}</span></div>
          <div className="datetime-row">
            <div className="input-with-icon native"><CalendarDays size={15}/><input type="date" aria-label="Departure date" required value={trip.date} onChange={e => set('date',e.target.value)}/></div>
            <div className="input-with-icon native"><Clock3 size={15}/><input type="time" aria-label="Departure time" required value={trip.time} onChange={e => set('time',e.target.value)}/></div>
          </div>
        </div>
        <div className="form-block"><label htmlFor="weight">Load weight</label>
          <div className="input-with-icon"><Package size={17}/><input id="weight" type="number" min="0" step="1" required value={trip.weight} onChange={e => set('weight',e.target.value)}/><span className="input-unit">lb</span></div>
        </div>
        <div className="form-block"><span className="field-label" id="spacing-label">Checkpoint spacing</span>
          <div className="intervals" role="group" aria-labelledby="spacing-label">{[10,25,50].map(miles =>
            <button aria-pressed={trip.intervalMiles === miles} key={miles} type="button" onClick={() => set('intervalMiles',miles)}>{miles} mi</button>
          )}</div>
        </div>
        <button className="calculate" type="submit">{busy ? <LoaderCircle className="spin" size={17}/> : <Navigation2 size={17}/>}<span>{busy ? 'Calculating routes…' : 'Calculate routes'}</span>{!busy && <ArrowRight size={17}/>}</button>
      </fieldset>
      {busy && <p className="working" role="status">Checking truck routes and hourly forecasts…</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
    <section className="side-legend"><div><h2>Weather risk scale</h2><button type="button" onClick={openGuide} aria-label="View weather risk thresholds">Guide <ArrowRight size={12}/></button></div>
      <ul>{riskLevels.map((level,i) => <li key={level}><span style={{background:riskColors[i]}}/>{level === 'Moderate' ? 'Mod.' : level === 'No Travel' ? 'No travel' : level}</li>)}</ul>
    </section>
  </aside>
}
