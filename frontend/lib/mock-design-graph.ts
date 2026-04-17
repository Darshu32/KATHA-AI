import type { DesignGraph, LayoutPreset } from "./types";

const MODERN_MATERIALS = [
  { id: "mat_floor_oak", name: "Oak Flooring", category: "wood", color: "#9b6b3d" },
  { id: "mat_wall_paint", name: "Warm White Paint", category: "paint", color: "#f2eee8" },
  { id: "mat_sofa_fabric", name: "Soft Beige Fabric", category: "fabric", color: "#d9c7b0" },
  { id: "mat_rug_wool", name: "Sand Wool Rug", category: "fabric", color: "#d8ccb9" },
  { id: "mat_metal_dark", name: "Dark Bronze Metal", category: "metal", color: "#5f5245" },
  { id: "mat_concrete", name: "Polished Concrete", category: "stone", color: "#b0b0b0" },
  { id: "mat_glass", name: "Clear Glass", category: "glass", color: "#d4eaf7" },
  { id: "mat_marble", name: "Carrara Marble", category: "stone", color: "#e8e4df" },
];

export const MOCK_LIVING_ROOM: DesignGraph = {
  room: {
    type: "living_room",
    dimensions: { length: 15, width: 12, height: 10, unit: "ft" },
  },
  style: {
    primary: "modern",
    secondary: ["warm", "functional"],
    color_palette: ["#9b6b3d", "#f2eee8", "#d9c7b0", "#d8ccb9", "#5f5245"],
    materials: ["Oak Flooring", "Warm White Paint", "Soft Beige Fabric"],
  },
  objects: [
    {
      id: "sofa_1",
      type: "sofa",
      name: "Main Sofa",
      position: { x: 4.5, y: 0, z: 8.5 },
      rotation: { x: 0, y: 0, z: 0 },
      dimensions: { length: 7, width: 3, height: 3 },
      material: "mat_sofa_fabric",
      color: "#d9c7b0",
    },
    {
      id: "table_1",
      type: "coffee_table",
      name: "Coffee Table",
      position: { x: 4.5, y: 0, z: 5.8 },
      rotation: { x: 0, y: 0, z: 0 },
      dimensions: { length: 3.5, width: 2, height: 1.4 },
      material: "mat_floor_oak",
      color: "#9b6b3d",
    },
    {
      id: "chair_1",
      type: "chair",
      name: "Accent Chair",
      position: { x: 9.2, y: 0, z: 6.5 },
      rotation: { x: 0, y: -0.6, z: 0 },
      dimensions: { length: 2.5, width: 2.5, height: 3 },
      material: "mat_sofa_fabric",
      color: "#d9c7b0",
    },
    {
      id: "rug_1",
      type: "rug",
      name: "Area Rug",
      position: { x: 4.8, y: 0.02, z: 6.7 },
      rotation: { x: 0, y: 0, z: 0 },
      dimensions: { length: 7.5, width: 5.5, height: 0.05 },
      material: "mat_rug_wool",
      color: "#d8ccb9",
    },
    {
      id: "console_1",
      type: "media_console",
      name: "Media Console",
      position: { x: 4.5, y: 0, z: 1.2 },
      rotation: { x: 0, y: 0, z: 0 },
      dimensions: { length: 1.3, width: 5.5, height: 2 },
      material: "mat_floor_oak",
      color: "#9b6b3d",
    },
    {
      id: "lamp_1",
      type: "floor_lamp",
      name: "Floor Lamp",
      position: { x: 10.5, y: 0, z: 8.2 },
      rotation: { x: 0, y: 0, z: 0 },
      dimensions: { length: 1.2, width: 1.2, height: 5.8 },
      material: "mat_metal_dark",
      color: "#5f5245",
    },
    {
      id: "plant_1",
      type: "plant",
      name: "Indoor Plant",
      position: { x: 12.2, y: 0, z: 2.2 },
      rotation: { x: 0, y: 0, z: 0 },
      dimensions: { length: 1.4, width: 1.4, height: 4.2 },
      material: "mat_metal_dark",
      color: "#758b57",
    },
    {
      id: "bookshelf_1",
      type: "bookshelf",
      name: "Bookshelf",
      position: { x: 13.5, y: 0, z: 6 },
      rotation: { x: 0, y: 1.57, z: 0 },
      dimensions: { length: 0.8, width: 3, height: 6 },
      material: "mat_floor_oak",
      color: "#9b6b3d",
    },
  ],
  materials: MODERN_MATERIALS,
  lighting: [
    { id: "light_ambient_1", type: "ambient", position: { x: 7.5, y: 9.5, z: 6 }, intensity: 0.7, color: "#fff4de" },
    { id: "light_floor_1", type: "point", position: { x: 10.5, y: 5, z: 8 }, intensity: 0.4, color: "#ffd7a8" },
  ],
  render_prompt_2d: "Modern living room with warm, practical furniture",
  render_prompt_3d: "Modern living room 3D scene with realistic spacing and circulation",
};

export const MOCK_2BHK: DesignGraph = {
  room: {
    type: "apartment_2bhk",
    dimensions: { length: 35, width: 28, height: 10, unit: "ft" },
  },
  style: {
    primary: "modern",
    secondary: ["functional", "compact"],
    color_palette: ["#9b6b3d", "#f2eee8", "#d9c7b0", "#7ca0b8"],
    materials: ["Oak Flooring", "White Paint", "Fabric"],
  },
  objects: [
    { id: "sofa_lr", type: "sofa", name: "Living Room Sofa", position: { x: 6, y: 0, z: 20 }, rotation: { x: 0, y: 0, z: 0 }, dimensions: { length: 6, width: 2.8, height: 2.8 }, material: "mat_sofa_fabric", color: "#d9c7b0" },
    { id: "tv_unit", type: "media_console", name: "TV Unit", position: { x: 6, y: 0, z: 15 }, rotation: { x: 0, y: 0, z: 0 }, dimensions: { length: 1.2, width: 5, height: 2 }, material: "mat_floor_oak", color: "#9b6b3d" },
    { id: "dining_table", type: "dining_table", name: "Dining Table", position: { x: 6, y: 0, z: 8 }, rotation: { x: 0, y: 0, z: 0 }, dimensions: { length: 4, width: 3, height: 2.5 }, material: "mat_floor_oak", color: "#9b6b3d" },
    { id: "chair_d1", type: "chair", name: "Dining Chair 1", position: { x: 4, y: 0, z: 8 }, rotation: { x: 0, y: 1.57, z: 0 }, dimensions: { length: 1.5, width: 1.5, height: 2.8 }, material: "mat_floor_oak", color: "#b08968" },
    { id: "chair_d2", type: "chair", name: "Dining Chair 2", position: { x: 8, y: 0, z: 8 }, rotation: { x: 0, y: -1.57, z: 0 }, dimensions: { length: 1.5, width: 1.5, height: 2.8 }, material: "mat_floor_oak", color: "#b08968" },
    { id: "bed_1", type: "bed", name: "Master Bed", position: { x: 26, y: 0, z: 22 }, rotation: { x: 0, y: 0, z: 0 }, dimensions: { length: 6.5, width: 5, height: 2 }, material: "mat_sofa_fabric", color: "#c4b5a2" },
    { id: "wardrobe_1", type: "wardrobe", name: "Master Wardrobe", position: { x: 33.5, y: 0, z: 22 }, rotation: { x: 0, y: 1.57, z: 0 }, dimensions: { length: 2, width: 6, height: 7 }, material: "mat_floor_oak", color: "#8b7355" },
    { id: "bed_2", type: "bed", name: "Bedroom 2 Bed", position: { x: 26, y: 0, z: 8 }, rotation: { x: 0, y: 0, z: 0 }, dimensions: { length: 6, width: 4.5, height: 2 }, material: "mat_sofa_fabric", color: "#7ca0b8" },
    { id: "desk_1", type: "desk", name: "Study Desk", position: { x: 33.5, y: 0, z: 8 }, rotation: { x: 0, y: 1.57, z: 0 }, dimensions: { length: 2, width: 3.5, height: 2.5 }, material: "mat_floor_oak", color: "#9b6b3d" },
    { id: "kitchen_counter", type: "counter", name: "Kitchen Counter", position: { x: 6, y: 0, z: 2.5 }, rotation: { x: 0, y: 0, z: 0 }, dimensions: { length: 2, width: 8, height: 3 }, material: "mat_marble", color: "#e8e4df" },
  ],
  materials: MODERN_MATERIALS,
  lighting: [
    { id: "light_main", type: "ambient", position: { x: 17.5, y: 9, z: 14 }, intensity: 0.8, color: "#fff8f0" },
    { id: "light_lr", type: "point", position: { x: 6, y: 8, z: 18 }, intensity: 0.5, color: "#ffeedd" },
    { id: "light_br1", type: "point", position: { x: 26, y: 8, z: 22 }, intensity: 0.4, color: "#fff4de" },
  ],
  render_prompt_2d: "Modern 2BHK apartment floor plan",
  render_prompt_3d: "Modern 2BHK apartment 3D view",
};

export const LAYOUT_PRESETS: LayoutPreset[] = [
  { id: "studio", label: "Studio", roomType: "studio", sqftRange: "300-400", rooms: "1 Room", description: "Open-plan studio apartment with combined living, sleeping, and kitchen areas", dims: { length: 20, width: 18 } },
  { id: "1bhk", label: "1 BHK", roomType: "apartment_1bhk", sqftRange: "450-650", rooms: "1 Bed + Hall + Kitchen", description: "Compact 1-bedroom apartment with separate living room and kitchen", dims: { length: 28, width: 22 } },
  { id: "2bhk", label: "2 BHK", roomType: "apartment_2bhk", sqftRange: "800-1100", rooms: "2 Bed + Hall + Kitchen", description: "Standard 2-bedroom apartment with living room, kitchen, and 2 bathrooms", dims: { length: 35, width: 28 } },
  { id: "3bhk", label: "3 BHK", roomType: "apartment_3bhk", sqftRange: "1200-1600", rooms: "3 Bed + Hall + Kitchen", description: "Spacious 3-bedroom apartment with separate dining area", dims: { length: 42, width: 35 } },
  { id: "4bhk", label: "4 BHK", roomType: "apartment_4bhk", sqftRange: "1800-2400", rooms: "4 Bed + Hall + Kitchen", description: "Large 4-bedroom apartment with servant room and utility area", dims: { length: 50, width: 42 } },
];

export function getMockGraphForPreset(presetId: string): DesignGraph {
  if (presetId === "2bhk") return MOCK_2BHK;
  return MOCK_LIVING_ROOM;
}
