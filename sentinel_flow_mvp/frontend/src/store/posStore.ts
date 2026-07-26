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
  // Phase 6: Backend ClinicalSafetyJudge verdict fields.
  // If is_safe_to_dispense is false, the pharmacist should NOT
  // proceed with the transaction until a senior pharmacist overrides.
  is_safe_to_dispense?: boolean;
  system_lock_reason?: string;
  // Phase 2: Disambiguation fields
  status?: string;
  // Beginner Note: Disambiguation choices used to be an array of plain strings.
  // The backend now returns a list of objects (e.g. { sku_id: "...", display_name: "..." }) 
  // so we can display readable names while using sku_ids under the hood.
  choices?: any[];
}

interface POSState {
  cart: CartItem[];
  isProcessing: boolean;
  isCopilotOpen: boolean;
  chatHistory: ChatMessage[];
  // Progressive Customer Identity
  customerPhone: string;
  customerName: string;
  customerId: string;
  // Phase 6: Safety lock — set by the CopilotPanel when the backend
  // ClinicalSafetyJudge blocks a transaction. Non-null means the
  // checkout buttons are disabled until a senior pharmacist overrides.
  activeSafetyLock: string | null;
  // Actions
  setSafetyLock: (reason: string | null) => void;
  clearSafetyLock: () => void;
  addItem: (item: Omit<CartItem, 'quantity'> & { quantity?: number }) => void;
  decrementItem: (batch_id: string) => void;
  removeItem: (batch_id: string) => void;
  clearCart: () => void;
  setProcessing: (status: boolean) => void;
  getTotal: () => number;
  toggleCopilot: () => void;
  addChatMessage: (msg: ChatMessage) => void;
  setCustomer: (phone: string, name: string, id: string) => void;
}

// Beginner Note: Zustand is a lightning-fast state manager. It allows any component
// in our app to access the cart without passing props down multiple levels.
export const usePOSStore = create<POSState>((set, get) => ({
  cart: [],
  isProcessing: false,
  isCopilotOpen: false,
  chatHistory: [],
  // Progressive Customer Identity — starts empty for anonymous sales
  customerPhone: '',
  customerName: '',
  customerId: '',
  // Phase 6: Safety lock starts null (unlocked). Set by CopilotPanel
  // when the backend returns is_safe_to_dispense=false.
  activeSafetyLock: null,

  // Phase 6: Called by CopilotPanel when the backend Judge blocks a
  // transaction. The reason (e.g. "CRITICAL_PREGNANCY_CONTRAINDICATION")
  // is stored so the POS page can display it in the lock banner.
  setSafetyLock: (reason: string | null) => set({ activeSafetyLock: reason }),

  // Phase 6: Called when a senior pharmacist clicks "Override Lock"
  // in the red checkout banner. Resets activeSafetyLock to null so
  // the checkout buttons become clickable again.
  clearSafetyLock: () => set({ activeSafetyLock: null }),

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

  clearCart: () => set({ cart: [], customerPhone: '', customerName: '', customerId: '', activeSafetyLock: null }),
  
  setProcessing: (status) => set({ isProcessing: status }),

  setCustomer: (phone, name, id) => set({ customerPhone: phone, customerName: name, customerId: id }),

  getTotal: () => {
    return get().cart.reduce((total, item) => total + (item.price * item.quantity), 0);
  }
}));
