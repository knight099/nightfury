export interface Brand {
  name: string;
  template: string;
}

export const BRANDS: Brand[] = [
  {
    name: "CP Plus",
    template:
      "rtsp://{user}:{pass}@{host}:554/cam/realmonitor?channel={ch}&subtype=0",
  },
  {
    name: "Hikvision",
    template: "rtsp://{user}:{pass}@{host}:554/Streaming/Channels/{ch}01",
  },
  {
    name: "Dahua",
    template:
      "rtsp://{user}:{pass}@{host}:554/cam/realmonitor?channel={ch}&subtype=0",
  },
  {
    name: "Reolink",
    template: "rtsp://{user}:{pass}@{host}:554/h264Preview_{ch}_main",
  },
  {
    name: "Tapo",
    template: "rtsp://{user}:{pass}@{host}:554/stream1",
  },
  {
    name: "Generic ONVIF",
    template: "rtsp://{user}:{pass}@{host}:554/onvif1",
  },
];
