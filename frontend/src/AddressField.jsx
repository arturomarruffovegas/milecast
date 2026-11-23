import React, { useEffect, useRef, useState } from 'react'
import { MapPin } from 'lucide-react'

export default function AddressField({ id, value, onChange }) {
  const [open, setOpen] = useState(false)
  const [places, setPlaces] = useState([])
  const [active, setActive] = useState(-1)
  const [message, setMessage] = useState('')
  const menu = useRef(null)
  const text = typeof value === 'string' ? value : value.name
  const query = text.trim()
  const searching = open && typeof value === 'string' && query.length >= 3 &&
    !/^[+-]?[\d.]+\s*,\s*[+-]?[\d.]*$/.test(query)

  useEffect(() => {
    if (!searching) return
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const response = await fetch('/api/places?' + new URLSearchParams({q: query}), {signal: controller.signal})
        const result = await response.json()
        if (controller.signal.aborted) return
        if (!response.ok) throw new Error(result.error || 'Address search is unavailable.')
        setPlaces(result.places)
        setMessage(result.places.length ? '' : 'No matching places. Add the city or ZIP code.')
      } catch (error) {
        if (!controller.signal.aborted) setMessage('Suggestions unavailable. You can still enter a full address or coordinates.')
      }
    }, 400)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query, searching])

  useEffect(() => {
    if (active >= 0) menu.current?.children[active]?.scrollIntoView({block:'nearest'})
  }, [active])

  function edit(next) {
    setActive(-1)
    setPlaces([])
    setMessage('Searching addresses…')
    setOpen(true)
    onChange(next)
  }

  function select(place) {
    setOpen(false)
    setActive(-1)
    onChange(place)
  }

  function handleKey(event) {
    if (event.key === 'Escape' && open) {
      event.preventDefault()
      setOpen(false)
      return
    }
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && typeof value === 'string' && query.length >= 3) {
      event.preventDefault()
      setOpen(true)
      if (places.length) {
        const next = event.key === 'ArrowDown' ? (active + 1) % places.length : (active <= 0 ? places.length - 1 : active - 1)
        setActive(next)
      }
    } else if (event.key === 'Enter' && searching && active >= 0 && places[active]) {
      event.preventDefault()
      select(places[active])
    }
  }

  return <div className="place-field">
    <div className="input-with-icon">
      {id === 'origin' ? <span className="origin-symbol"/> : <MapPin size={17} className="destination-icon"/>}
      <input id={id} type="text" role="combobox" autoComplete="off" aria-autocomplete="list"
        aria-expanded={searching} aria-controls={searching ? id + '-choices' : undefined}
        aria-activedescendant={searching && active >= 0 ? id + '-place-' + active : undefined}
        value={text} onChange={e => edit(e.target.value)} onKeyDown={handleKey}
        onFocus={() => {setOpen(true);setActive(-1);setPlaces([]);setMessage('Searching addresses…')}}
        onBlur={() => {setOpen(false);setActive(-1)}}
        placeholder="Street address, city, or ZIP" required maxLength={160}/>
    </div>
    {searching && <div className="place-menu">
      <ul ref={menu} role="listbox" id={id + '-choices'} aria-label={id + ' suggestions'}>
        {places.map((place, i) => {
          const [first, ...rest] = place.name.split(', ')
          return <li key={i} role="option" aria-selected={active === i} id={id + '-place-' + i}
            onMouseDown={e => e.preventDefault()} onClick={() => select(place)}>
            <MapPin size={15}/><div><strong>{first}</strong>{rest.length > 0 && <span>{rest.join(', ')}</span>}</div>
          </li>
        })}
      </ul>
      {message && <p role="status">{message}</p>}
    </div>}
  </div>
}
