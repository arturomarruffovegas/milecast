import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  ArrowRight, BookOpen, Check, ChevronRight, CircleHelp, CloudSun, Clock3, Crosshair,
  Database, Flag, Map as MapIcon, MapPinned, Milestone, Pause, Play, Route, ShieldCheck, Truck, Wind, CloudRain, Snowflake,
} from 'lucide-react'
import TripForm, { initialTrip } from './TripForm'
import RouteMap from './RouteMap'
import Details, { RiskPill } from './Details'
import { displayTime, journeyTime, placeName, riskLevels, routeColors } from './format'
import './styles.css'

function Header({setDialog}) {
  return <header className="app-header">
    <div className="brand"><img src={import.meta.env.BASE_URL + 'favicon.svg'} alt=""/><span>Milecast</span></div>
    <div className="header-divider"/>
    <span className="workspace-nav"><Route size={17}/> Route planner</span>
    <nav aria-label="Resources"><button onClick={() => setDialog('guide')}><BookOpen size={15}/> Risk guide</button><button onClick={() => setDialog('sources')}><Database size={15}/> Data sources</button></nav>
  </header>
}

function ForecastBar({plan, hour, setHour, playing, setPlaying}) {
  const forecastTime = new Date(new Date(plan.heatmap.start).getTime() + hour * 3600000)
  return <div className="forecast-bar">
    <button className={'play' + (playing ? ' active' : '')} aria-label={playing ? 'Pause forecast' : 'Play forecast'} onClick={() => setPlaying(p => !p)}>{playing ? <Pause size={16} fill="currentColor"/> : <Play size={15} fill="currentColor"/>}</button>
    <div className="forecast-content"><div className="forecast-caption"><strong>Forecast timeline</strong><span>{displayTime(forecastTime,true)}</span></div>
      <input aria-label="Forecast hour after departure" aria-valuetext={hour + ' hours after departure'} type="range" min="0" max="48" step="1" value={hour} style={{'--progress':(hour / 48 * 100) + '%'}} onChange={e => {setPlaying(false);setHour(Number(e.target.value))}}/>
      <div className="ticks" aria-hidden="true"><span>Departure</span><span>+12h</span><span>+24h</span><span>+36h</span><span>+48h</span></div>
    </div>
  </div>
}

function CorridorWeather({ heatmap, hour }) {
  const peaks = heatmap.hourlyPeaks?.[hour]
  if (!peaks) return null
  const highest = Math.max(...heatmap.points.map(point => riskLevels.indexOf(point.risks[hour])))
  return <section className="corridor-weather" aria-label="Hourly corridor weather">
    <div className="weather-caption"><strong>Corridor weather</strong><span>Open-Meteo · {heatmap.points.length} locations</span></div>
    <dl className="weather-metrics">
      <div><dt><Wind/> Peak wind</dt><dd>{peaks.windMph.toFixed(1)} mph</dd></div>
      <div><dt><CloudRain/> Peak rain</dt><dd>{peaks.rainInHr.toFixed(3)} in/h</dd></div>
      <div><dt><Snowflake/> Peak snow</dt><dd>{peaks.snowInHr.toFixed(3)} in/h</dd></div>
    </dl>
    <div className="peak-risk"><span>Highest risk</span><RiskPill risk={riskLevels[highest]}/></div>
  </section>
}

function RouteCard({route, i, selected, recommended, choose, inspect}) {
  return <article className={'route-card' + (selected ? ' selected' : '')} style={{'--route-color':routeColors[i % routeColors.length]}}>
    <button className="card-select" aria-pressed={selected} aria-label={'Show route ' + (i + 1) + ' via ' + route.name} onClick={choose}>
      <div className="card-top"><span className="route-key"><i/>Route {i+1}</span>{recommended && <span className="recommended"><ShieldCheck size={12}/> Recommended</span>}</div>
      <h3 title={route.name}>{route.name}</h3>
      <div className="card-stats"><span><Clock3/>{journeyTime(route.durationMinutes)}</span><i/><span><Milestone/>{Math.round(route.distanceMiles)} mi</span></div>
    </button>
    <div className="card-foot"><RiskPill risk={route.risk}/><button onClick={inspect} aria-label={'View checkpoints for route ' + (i+1)}>Checkpoints <ChevronRight size={13}/></button></div>
  </article>
}

function App() {
  const [trip,setTrip] = useState(initialTrip)
  const [plan,setPlan] = useState(null)
  const [example,setExample] = useState(true)
  const [selectedId,setSelectedId] = useState(null)
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const [showHeat,setShowHeat] = useState(true)
  const [hour,setHour] = useState(0)
  const [playing,setPlaying] = useState(false)
  const [fitSignal,setFitSignal] = useState(0)
  const [dialog,setDialog] = useState(null)
  const requested = useRef(false)
  const sending = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch(import.meta.env.BASE_URL + 'example-trip.json', { signal:controller.signal }).then(r => {
      if (!r.ok) throw new Error('Example unavailable')
      return r.json()
    }).then(exampleTrip => {
      if (requested.current) return
      setPlan(exampleTrip)
      setSelectedId(exampleTrip.recommendedId || exampleTrip.routes[0].id)
    }).catch(() => {})
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!playing || !showHeat) return
    const interval = setInterval(() => setHour(h => (h + 1) % 49), 800)
    return () => clearInterval(interval)
  }, [playing,showHeat])

  async function submit(event) {
    event.preventDefault()
    if (sending.current) return
    const date = new Date(trip.date + 'T' + trip.time)
    if (!Number.isFinite(date.getTime())) {setError('Enter a valid departure date and time.');return}
    requested.current = true
    sending.current = true
    setError('')
    setBusy(true)
    setPlaying(false)
    try {
      const response = await fetch('/api/plan', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({origin:trip.origin,destination:trip.destination,departure:date.toISOString(),loadLb:Number(trip.weight),intervalMiles:trip.intervalMiles}),
        signal: AbortSignal.timeout(115000),
      })
      const result = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(result.error || 'The routing service is unavailable. Please try again.')
      setPlan(result)
      setSelectedId(result.recommendedId || result.routes[0].id)
      setExample(false)
      setHour(0)
      setFitSignal(v => v + 1)
    } catch (e) {
      setPlan(null)
      setSelectedId(null)
      setError(e.name === 'TimeoutError' ? 'The trip took too long to calculate. Please try again.' : e instanceof TypeError ? 'Could not reach the planner. Check your connection and try again.' : e.message)
    } finally {sending.current = false;setBusy(false)}
  }
  const selectedRoute = plan?.routes.find(r => r.id === selectedId)
  return <>
    <Header setDialog={setDialog}/>
    <div className="workspace">
      <TripForm trip={trip} change={setTrip} submit={submit} busy={busy} error={error} openGuide={() => setDialog('guide')}/>
      <main className="results">
        <div className="trip-heading">
          <div><div className="map-kicker"><MapPinned size={14}/> Route overview</div>
            <h2>{plan ? <><span>{placeName(plan.origin)}</span><ArrowRight size={25}/><span>{placeName(plan.destination)}</span></> : 'Plan a truck route'}</h2>
          </div>
          {plan && <span className={'forecast-status' + (example ? '' : ' live')} title={example ? 'Saved Open-Meteo forecast. Calculate routes for your departure time.' : 'Calculated with hourly Open-Meteo forecasts for this trip.'}>{example ? <BookOpen size={13}/> : <Check size={14}/>} {example ? 'Saved example forecast' : 'Open-Meteo forecast'}</span>}
        </div>
        {error && !plan ? <section className="empty-forecast"><MapPinned size={32}/><h3>No forecast for this trip</h3><p>Update the trip details and calculate routes again.</p></section> : <section className="map-frame" aria-label="Interactive route map">
          <RouteMap plan={plan} selectedId={selectedId} onSelect={setSelectedId} showHeat={showHeat} hour={hour} fitSignal={fitSignal}/>
          {plan && <>
            <div className="layer-options" aria-label="Map layers"><button aria-pressed={!showHeat} onClick={() => {setShowHeat(false);setPlaying(false)}}><MapIcon size={15}/> Routes</button><button aria-pressed={showHeat} onClick={() => setShowHeat(true)}><CloudSun size={16}/> Weather risk</button></div>
            <button className="fit-map" title="Fit all routes" aria-label="Fit all routes" onClick={() => setFitSignal(i => i + 1)}><Crosshair size={17}/></button>
            {showHeat && <ForecastBar plan={plan} hour={hour} setHour={setHour} playing={playing} setPlaying={setPlaying}/>}
          </>}
        </section>}
        {plan && <>
          {showHeat && <CorridorWeather heatmap={plan.heatmap} hour={hour}/>}
          <div className="trip-strip"><span><Flag/> {displayTime(plan.departure,true)}</span><i/><span><Truck/> {plan.loadLb.toLocaleString('en-US')} lb</span><i/><span><Milestone/> Every {plan.intervalMiles} mi</span></div>
          {plan.warnings.map(msg => <p key={msg} className="notice" role="status">{msg}</p>)}
          <section className="options">
            <div className="options-head"><h2>Route options <span>{plan.routes.length}</span></h2><button onClick={() => setDialog('guide')}><CircleHelp size={14}/> How ranking works</button></div>
            <div className="cards">{plan.routes.map((r,i) => <RouteCard key={r.id} route={r} i={i} selected={r.id === selectedId} recommended={r.id === plan.recommendedId} choose={() => setSelectedId(r.id)} inspect={() => {setSelectedId(r.id);setDialog('checkpoints')}}/>)}</div>
          </section>
        </>}
      </main>
    </div>
    {dialog && <Details view={dialog} route={selectedRoute} isExample={example} close={() => setDialog(null)}/>}
  </>
}

createRoot(document.getElementById('root')).render(<App/>)
