// v53 primitive — THE text input (.ui-input): one border/radius/padding for every
// form field (screens previously each restyled inputs with 5px/8px radii ad-hoc).
import type { InputHTMLAttributes } from 'react'

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={className ? `ui-input ${className}` : 'ui-input'} {...rest} />
}
