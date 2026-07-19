// v53 primitive — THE button. Thin wrapper over the section-3 CSS classes (.btn family +
// .chip) so visuals stay in App.css; every action button in views goes through this
// (App.css header rule: no new button classes). `type` defaults to "button" so a Button
// inside a <form> never submits by accident — pass type="submit" explicitly.
import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'danger' | 'ghost' | 'chip'

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'btn btn-primary',
  danger: 'btn btn-danger',
  ghost: 'btn',
  chip: 'chip',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

export function Button({ variant = 'ghost', className, type = 'button', ...rest }: ButtonProps) {
  const cls = className ? `${VARIANT_CLASS[variant]} ${className}` : VARIANT_CLASS[variant]
  return <button type={type} className={cls} {...rest} />
}
