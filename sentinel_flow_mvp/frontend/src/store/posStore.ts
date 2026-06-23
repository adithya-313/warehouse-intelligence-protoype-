import { create } from 'zustand';

// Beginner Note: We define the shape of an item in our cart.
export interface CartItem {
  batch_id: string;
  sku_id: string;
  name: string;
  price: number;
  quantity: number;
}

interface POSState {
  cart: CartItem[];
  isProcessing: boolean;
  // Actions
  addItem: (item: Omit<CartItem, 'quantity'>) => void;
  removeItem: (batch_id: string) => void;
  clearCart: () => void;
  setProcessing: (status: boolean) => void;
  getTotal: () => number;
}

// Beginner Note: Zustand is a lightning-fast state manager. It allows any component
// in our app to access the cart without passing props down multiple levels.
export const usePOSStore = create<POSState>((set, get) => ({
  cart: [],
  isProcessing: false,

  addItem: (newItem) => set((state) => {
    const existingItem = state.cart.find(item => item.batch_id === newItem.batch_id);
    if (existingItem) {
      // If it exists, just increase the quantity (immutable update)
      return {
        cart: state.cart.map(item => 
          item.batch_id === newItem.batch_id 
            ? { ...item, quantity: item.quantity + 1 } 
            : item
        )
      };
    }
    // If it's new, add it to the cart with quantity 1
    return { cart: [...state.cart, { ...newItem, quantity: 1 }] };
  }),

  removeItem: (batch_id) => set((state) => ({
    cart: state.cart.filter(item => item.batch_id !== batch_id)
  })),

  clearCart: () => set({ cart: [] }),
  
  setProcessing: (status) => set({ isProcessing: status }),

  getTotal: () => {
    return get().cart.reduce((total, item) => total + (item.price * item.quantity), 0);
  }
}));
