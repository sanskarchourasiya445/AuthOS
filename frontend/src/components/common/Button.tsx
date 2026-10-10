import React from 'react'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'success' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  isLoading?: boolean
  icon?: React.ReactNode
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary',
  size = 'md',
  isLoading = false,
  icon,
  children,
  className = '',
  disabled,
  ...props
}) => {
  const sizeClasses = {
    sm: 'text-xs py-1 px-2.5',
    md: 'text-sm py-2 px-3.5',
    lg: 'text-base py-2.5 px-4',
  }[size]

  return (
    <button
      className={`btn btn-${variant} ${sizeClasses} ${className}`.trim()}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <span
          className="loading-spinner"
          aria-hidden="true"
          style={{
            display: 'inline-block',
            width: '12px',
            height: '12px',
            border: '2px solid currentColor',
            borderRightColor: 'transparent',
            borderRadius: '50%',
            animation: 'spin 0.75s linear infinite',
          }}
        />
      ) : (
        icon
      )}
      <span>{children}</span>
    </button>
  )
}
