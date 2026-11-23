import React, { useEffect, useRef } from 'react'
import { Database, ExternalLink, Milestone, ShieldCheck, X } from 'lucide-react'
import { displayTime, journeyTime, riskColors, riskLevels } from './format'

export function RiskPill({risk}) {
  const index = riskLevels.indexOf(risk)
  return <span className={'risk-pill risk-' + index}><i style={{background:riskColors[index]}}/>{risk}{risk === 'No Travel' ? '' : ' risk'}</span>
}

export default function Details({view, route, isExample, close}) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    el.showModal()
    return () => el.close()
  }, [])
  const checkpointView = view === 'checkpoints'
  const title = checkpointView ? 'Route checkpoints' : view === 'sources' ? 'Data sources' : 'Weather risk guide'
  return <dialog ref={ref} onCancel={close} onClick={e => {if (e.target === ref.current) close()}} aria-labelledby="dialog-title" className="details-dialog">
    <div className="dialog-shell">
      <header><span className="section-icon">{checkpointView ? <Milestone/> : view === 'sources' ? <Database/> : <ShieldCheck/>}</span><h2 id="dialog-title">{title}</h2><button className="icon-button x" aria-label="Close dialog" onClick={close}><X size={19}/></button></header>
      {checkpointView ? <>
        <p>{route.name} · {Math.round(route.distanceMiles)} mi · {journeyTime(route.durationMinutes)}{isExample ? ' · Example forecast' : ''}</p>
        <div className="exposure"><span><b>{route.highMiles.toFixed(1)} mi</b> High</span><span><b>{route.severeMiles.toFixed(1)} mi</b> Severe</span><span><b>{route.noTravelMiles.toFixed(1)} mi</b> No Travel</span></div>
        <div className="table-pan"><table><caption>Hourly forecasts at estimated arrival</caption><thead><tr>{['Mile','ETA','Wind','Rain','Snow','Risk'].map(c => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{route.checkpoints.map((p,i) => <tr key={i}><td>{p.mile.toFixed(1)}</td><td>{displayTime(p.eta,true)}</td><td>{p.windMph.toFixed(1)} mph</td><td>{p.rainInHr.toFixed(2)} in/h</td><td>{p.snowInHr.toFixed(2)} in/h</td><td><RiskPill risk={p.risk}/></td></tr>)}</tbody></table></div>
      </> : view === 'sources' ? <>
        <div className="source-list">{[
          ['Truck routing','Valhalla uses OpenStreetMap roads and truck-access data to estimate routes and driving times.','https://valhalla.github.io/valhalla/'],
          ['Long-distance waypoints','OSRM identifies candidate junctions on long trips. Valhalla calculates the truck route and travel time for each leg.','https://project-osrm.org/'],
          ['Weather forecasts','Open-Meteo supplies hourly wind, rainfall, and snowfall for the trip corridor.','https://open-meteo.com/en/docs'],
          ['Address suggestions','Photon searches OpenStreetMap for street addresses, businesses, and places.','https://photon.komoot.io/'],
          ['U.S. street addresses','The U.S. Census Geocoder can resolve additional U.S. street addresses.','https://geocoding.geo.census.gov/geocoder/'],
          ['Map data','OpenStreetMap contributors maintain the roads, places, and geographic features on the map.','https://www.openstreetmap.org/copyright'],
        ].map(([name,copy,url]) => <section key={name}><a href={url} target="_blank" rel="noreferrer">{name}<ExternalLink size={13}/></a><p>{copy}</p></section>)}</div>
        <p className="dialog-note">The opening example uses a saved Open-Meteo forecast. Calculate a trip for your departure time. The slider shows corridor weather in the selected hour. Checkpoints show the forecast at each truck arrival time.</p>
      </> : <>
        <p>Each checkpoint takes the highest risk from wind, rain, and snow at the truck’s ETA. Load weight can raise the wind risk.</p>
        <div className="table-pan"><table><thead><tr><th>Risk</th><th>Wind · mph</th><th>Rain · in/h</th><th>Snow · in/h</th></tr></thead>
          <tbody>{[['< 25','< 0.10','< 0.5'],['25–<35','0.10–<0.25','0.5–<1.0'],['35–<45','0.25–<0.50','1.0–<2.0'],['45–<55','0.50–1.00','2.0–3.0'],['≥ 55','> 1.00','> 3.0']].map((values,i) => <tr key={i}><td><RiskPill risk={riskLevels[i]}/></td>{values.map((v,j) => <td key={j}>{v}</td>)}</tr>)}</tbody></table></div>
        <h3>Load adjustments</h3><p>At winds of 35 to under 45 mph, loads over 40,000 lb reach Severe. At 45 to under 55 mph, loads over 30,000 lb reach No Travel. Winds of 55 mph or more stop travel at every weight.</p>
        <h3>How routes are ranked</h3><p>Routes with No Travel checkpoints are ineligible for recommendation. Among the rest, Milecast compares Severe miles, then High miles, distance-weighted average risk, and finally driving time.</p>
        <p className="dialog-note">Driving estimates exclude stops and rest breaks. Confirm current closures and restrictions before departure.</p>
      </>}
    </div>
  </dialog>
}
