import { forwardRef } from 'react'
import { Button, type ButtonProps } from 'antd'

/** Shared press, hover and click feedback; retains Ant Design's loading semantics. */
export const ActionButton = forwardRef<HTMLButtonElement, ButtonProps>(function ActionButton(
  { className = '', ...props }, ref,
) {
  return <Button {...props} ref={ref} data-click-spark className={`mnemox-action-button ${className}`} />
})
