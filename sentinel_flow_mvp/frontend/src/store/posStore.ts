import { create } from 'zustand';

// Beginner Note: We define the shape of an item in our cart.
export interface CartItem {
  batch_id: string;
  sku_id: string;
  name: string;
  price: number;
  quantity: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  content: string;
  sources?: any[];
}

interface POSState {
  cart: CartItem[];
  isProcessing: boolean;
  isCopilotOpen: boolean;
  chatHistory: ChatMessage[];
  // Actions
  addItem: (item: Omit<CartItem, 'quantity'> & { quantity?: number }) => void;
  decrementItem: (batch_id: string) => void;
  removeItem: (batch_id: string) => void;
  clearCart: () => void;
  setProcessing: (status: boolean) => void;
  getTotal: () => number;
  toggleCopilot: () => void;
  addChatMessage: (msg: ChatMessage) => void;
}

// Beginner Note: Zustand is a lightning-fast state manager. It allows any component
// in our app to access the cart without passing props down multiple levels.
export const usePOSStore = create<POSState>((set, get) => ({
  cart: [],
  isProcessing: false,
  isCopilotOpen: false,
  chatHistory: [],

  toggleCopilot: () => set((state) => ({ isCopilotOpen: !state.isCopilotOpen })),
  addChatMessage: (msg) => set((state) => ({ chatHistory: [...state.chatHistory, msg] })),

  // Step 1: Add a new item to the cart or increment its quantity if it already exists.
  // We allow passing an optional custom quantity, defaulting to 1.
  addItem: (newItem) => set((state) => {
    const quantityToAdd = newItem.quantity || 1;
    const existingItem = state.cart.find(item => item.batch_id === newItem.batch_id);
    
    if (existingItem) {
      // Step 2: If the item already exists in the cart, create a new array with the updated quantity.
      const updatedCart = state.cart.map(item => 
        item.batch_id === newItem.batch_id 
          ? { ...item, quantity: item.quantity + quantityToAdd } 
          : item
      );
      return { cart: updatedCart };
    }
    
    // Step 3: If the item is new, append it to the end of the cart array.
    const cartItemToAdd: CartItem = {
      batch_id: newItem.batch_id,
      sku_id: newItem.sku_id,
      name: newItem.name,
      price: newItem.price,
      quantity: quantityToAdd
    };
    
    return { cart: [...state.cart, cartItemToAdd] };
  }),

  // Step 4: Decrease the quantity of an item by 1.
  // If the resulting quantity drops to 0, completely remove the item from the cart.
  decrementItem: (batch_id) => set((state) => {
    const existingItem = state.cart.find(item => item.batch_id === batch_id);
    
    if (existingItem && existingItem.quantity > 1) {
      // The quantity is above 1, so we just reduce it by 1 safely.
      const reducedCart = state.cart.map(item => 
        item.batch_id === batch_id 
          ? { ...item, quantity: item.quantity - 1 } 
          : item
      );
      return { cart: reducedCart };
    }
    
    // The quantity is 1 (or less), so removing 1 means it hits 0. We filter it out completely.
    const filteredCart = state.cart.filter(item => item.batch_id !== batch_id);
    return { cart: filteredCart };
  }),

  // Step 5: Immediately remove the item from the cart regardless of its quantity.
  removeItem: (batch_id) => set((state) => ({
    cart: state.cart.filter(item => item.batch_id !== batch_id)
  })),

  clearCart: () => set({ cart: [] }),
  
  setProcessing: (status) => set({ isProcessing: status }),

  getTotal: () => {
    return get().cart.reduce((total, item) => total + (item.price * item.quantity), 0);
  }
}));
