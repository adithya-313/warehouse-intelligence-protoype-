import { useEffect, useRef } from 'react';

/**
 * Beginner Note: A physical barcode scanner acts exactly like a very fast keyboard.
 * It types the barcode characters in milliseconds and presses 'Enter'.
 * This hook listens to all keystrokes globally. If it detects rapid typing ending
 * in 'Enter', it assumes it's a scanner and triggers the callback.
 */
export function useHardwareScanner(onScan: (barcode: string) => void) {
  const barcodeBuffer = useRef<string>('');
  const lastKeyTime = useRef<number>(0);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const currentTime = new Date().getTime();
      
      // If more than 50ms has passed since the last key, it's probably a human typing.
      // We clear the buffer to ignore human input.
      if (currentTime - lastKeyTime.current > 50) {
        barcodeBuffer.current = '';
      }

      // If the scanner presses 'Enter', we have a complete barcode.
      if (e.key === 'Enter' && barcodeBuffer.current.length > 3) {
        onScan(barcodeBuffer.current);
        barcodeBuffer.current = ''; // Reset for the next scan
        e.preventDefault();
      } else if (e.key.length === 1) {
        // Add the character to our buffer
        barcodeBuffer.current += e.key;
      }

      lastKeyTime.current = currentTime;
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onScan]);
}
