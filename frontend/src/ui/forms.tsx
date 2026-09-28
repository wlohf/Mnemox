import {
  forwardRef,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'
import * as RSelect from '@radix-ui/react-select'
import * as RSwitch from '@radix-ui/react-switch'
import * as RCheckbox from '@radix-ui/react-checkbox'
import * as RRadio from '@radix-ui/react-radio-group'
import * as RSlider from '@radix-ui/react-slider'
import { Check, ChevronDown, CircleAlert, Minus } from 'lucide-react'
import { cx } from './controls'
import s from './forms.module.css'

/* ---------- Field (label + hint + error wiring) ---------- */
export function Field({
  label,
  hint,
  error,
  optional,
  htmlFor,
  aside,
  children,
  className,
}: {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  optional?: boolean
  htmlFor?: string
  aside?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cx(s.field, className)}>
      {(label || aside) && (
        <div className={s.fieldLabelRow}>
          {label && (
            <label className={s.label} htmlFor={htmlFor}>
              {label}
              {optional && <span className={s.optional}>可选</span>}
            </label>
          )}
          {aside}
        </div>
      )}
      {children}
      {error ? (
        <span className={s.error} role="alert">
          <CircleAlert aria-hidden />
          {error}
        </span>
      ) : hint ? (
        <span className={s.hint}>{hint}</span>
      ) : null}
    </div>
  )
}

/* ---------- Input ---------- */
export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'prefix'> {
  size?: 'sm' | 'md' | 'lg'
  prefix?: ReactNode
  suffix?: ReactNode
  invalid?: boolean
  wrapperClassName?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { size = 'md', prefix, suffix, invalid, disabled, className, wrapperClassName, ...rest },
  ref,
) {
  return (
    <div
      className={cx(s.control, wrapperClassName)}
      data-size={size}
      data-invalid={invalid || undefined}
      data-disabled={disabled || undefined}
    >
      {prefix && <span className={s.affix}>{prefix}</span>}
      <input
        ref={ref}
        className={cx(s.input, className)}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        {...rest}
      />
      {suffix && <span className={s.affix}>{suffix}</span>}
    </div>
  )
})

/* ---------- Textarea (optionally auto-growing) ---------- */
export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean
  autoGrow?: boolean
  maxHeight?: number
  reading?: boolean
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { invalid, autoGrow, maxHeight = 320, reading, className, value, style, ...rest },
  ref,
) {
  const inner = useRef<HTMLTextAreaElement | null>(null)
  useLayoutEffect(() => {
    if (!autoGrow || !inner.current) return
    const el = inner.current
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight + 2, maxHeight)}px`
  }, [autoGrow, maxHeight, value])
  return (
    <textarea
      ref={node => {
        inner.current = node
        if (typeof ref === 'function') ref(node)
        else if (ref) ref.current = node
      }}
      className={cx(s.textarea, className)}
      data-invalid={invalid || undefined}
      data-reading={reading || undefined}
      aria-invalid={invalid || undefined}
      value={value}
      style={autoGrow ? { resize: 'none', overflowY: 'auto', ...style } : style}
      {...rest}
    />
  )
})

/* ---------- Select ---------- */
export interface SelectOption {
  value: string
  label: ReactNode
  hint?: ReactNode
  disabled?: boolean
}
export interface SelectGroup {
  label: string
  options: SelectOption[]
}

export function Select({
  value,
  onValueChange,
  options,
  groups,
  placeholder = '请选择',
  size = 'md',
  disabled,
  id,
  className,
  ariaLabel,
  invalid,
}: {
  value?: string
  onValueChange: (v: string) => void
  options?: SelectOption[]
  groups?: SelectGroup[]
  placeholder?: string
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  id?: string
  className?: string
  ariaLabel?: string
  invalid?: boolean
}) {
  const renderItem = (o: SelectOption) => (
    <RSelect.Item key={o.value} value={o.value} disabled={o.disabled} className={s.selectItem}>
      <RSelect.ItemText>{o.label}</RSelect.ItemText>
      {o.hint && <span className={s.selectItemHint}>{o.hint}</span>}
      <RSelect.ItemIndicator className={s.selectItemIndicator}>
        <Check />
      </RSelect.ItemIndicator>
    </RSelect.Item>
  )
  return (
    <RSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RSelect.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cx(s.control, s.selectTrigger, className)}
        data-size={size}
        data-invalid={invalid || undefined}
        data-disabled={disabled || undefined}
      >
        <RSelect.Value placeholder={placeholder} />
        <RSelect.Icon asChild>
          <ChevronDown />
        </RSelect.Icon>
      </RSelect.Trigger>
      <RSelect.Portal>
        <RSelect.Content className={s.selectContent} position="popper" sideOffset={6} collisionPadding={8}>
          <RSelect.Viewport className={s.selectViewport}>
            {options?.map(renderItem)}
            {groups?.map((g, i) => (
              <RSelect.Group key={g.label}>
                {i > 0 && <RSelect.Separator className={s.selectSeparator} />}
                <RSelect.Label className={s.selectGroupLabel}>{g.label}</RSelect.Label>
                {g.options.map(renderItem)}
              </RSelect.Group>
            ))}
          </RSelect.Viewport>
        </RSelect.Content>
      </RSelect.Portal>
    </RSelect.Root>
  )
}

/* ---------- Switch ---------- */
export function Switch({
  checked,
  onCheckedChange,
  disabled,
  id,
  ariaLabel,
}: {
  checked: boolean
  onCheckedChange: (v: boolean) => void
  disabled?: boolean
  id?: string
  ariaLabel?: string
}) {
  return (
    <RSwitch.Root
      id={id}
      className={s.switch}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={ariaLabel}
    >
      <RSwitch.Thumb className={s.switchThumb} />
    </RSwitch.Root>
  )
}

/** A labelled switch row for settings lists. */
export function SwitchField({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
}: {
  label: ReactNode
  description?: ReactNode
  checked: boolean
  onCheckedChange: (v: boolean) => void
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className={s.switchRow}>
      <span className={s.switchText}>
        <label className={s.label} htmlFor={id}>
          {label}
        </label>
        {description && <span className={s.hint}>{description}</span>}
      </span>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
    </div>
  )
}

/* ---------- Checkbox ---------- */
export function Checkbox({
  checked,
  onCheckedChange,
  label,
  disabled,
  indeterminate,
}: {
  checked: boolean
  onCheckedChange: (v: boolean) => void
  label?: ReactNode
  disabled?: boolean
  indeterminate?: boolean
}) {
  const id = useId()
  return (
    <label className={s.checkRow} htmlFor={id} data-disabled={disabled || undefined}>
      <RCheckbox.Root
        id={id}
        className={s.checkbox}
        checked={indeterminate ? 'indeterminate' : checked}
        onCheckedChange={v => onCheckedChange(v === true)}
        disabled={disabled}
      >
        <RCheckbox.Indicator>{indeterminate ? <Minus /> : <Check />}</RCheckbox.Indicator>
      </RCheckbox.Root>
      {label}
    </label>
  )
}

/* ---------- Radio cards ---------- */
export function RadioCards<T extends string>({
  value,
  onValueChange,
  options,
  columns = 1,
  ariaLabel,
}: {
  value: T
  onValueChange: (v: T) => void
  options: Array<{ value: T; title: ReactNode; description?: ReactNode; disabled?: boolean }>
  columns?: number
  ariaLabel?: string
}) {
  return (
    <RRadio.Root
      className={s.radioGroup}
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
      value={value}
      onValueChange={v => onValueChange(v as T)}
      aria-label={ariaLabel}
    >
      {options.map(o => (
        <RRadio.Item key={o.value} value={o.value} disabled={o.disabled} className={s.radioCard}>
          <span className={s.radioDot} aria-hidden />
          <span>
            <span className={s.radioTitle}>{o.title}</span>
            {o.description && <span className={s.radioDesc}>{o.description}</span>}
          </span>
        </RRadio.Item>
      ))}
    </RRadio.Root>
  )
}

/* ---------- Segmented control ---------- */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = 'md',
  block,
  ariaLabel,
}: {
  value: T
  onChange: (v: T) => void
  options: Array<{ value: T; label: ReactNode; icon?: ReactNode }>
  size?: 'sm' | 'md'
  block?: boolean
  ariaLabel?: string
}) {
  const wrap = useRef<HTMLDivElement | null>(null)
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null)
  useLayoutEffect(() => {
    const el = wrap.current?.querySelector<HTMLElement>('[aria-checked="true"]')
    if (!el || !wrap.current) return
    const measure = () => setThumb({ x: el.offsetLeft, w: el.offsetWidth })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [value, options.length])
  return (
    <div
      ref={wrap}
      role="radiogroup"
      aria-label={ariaLabel}
      className={s.segmented}
      data-size={size}
      data-block={block || undefined}
      onKeyDown={e => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
        e.preventDefault()
        const i = options.findIndex(o => o.value === value)
        const next = options[(i + (e.key === 'ArrowRight' ? 1 : options.length - 1)) % options.length]
        onChange(next.value)
        requestAnimationFrame(() => wrap.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus())
      }}
    >
      {thumb && (
        <span
          aria-hidden
          className={s.segmentThumb}
          style={{ width: thumb.w, transform: `translateX(${thumb.x - 3}px)`, left: 3 } as CSSProperties}
        />
      )}
      {options.map(o => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          className={s.segment}
          onClick={() => onChange(o.value)}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* ---------- Slider ---------- */
export function Slider({
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  ariaLabel,
  disabled,
}: {
  value: number
  onValueChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  ariaLabel?: string
  disabled?: boolean
}) {
  return (
    <RSlider.Root
      className={s.slider}
      value={[value]}
      onValueChange={v => onValueChange(v[0])}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
    >
      <RSlider.Track className={s.sliderTrack}>
        <RSlider.Range className={s.sliderRange} />
      </RSlider.Track>
      <RSlider.Thumb className={s.sliderThumb} aria-label={ariaLabel} />
    </RSlider.Root>
  )
}
