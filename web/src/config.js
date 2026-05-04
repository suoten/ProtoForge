const config = {
  edgeLite: {
    unsupportedProtocols: ['gb28181', 'bacnet', 'profinet', 'ethercat'],
    defaultCollectInterval: 5,
    defaultUrl: '',
  },
  sdk: {
    examples: {
      python: `# ProtoForge Python SDK
from protoforge.sdk import ProtoForgeClient

with ProtoForgeClient("http://localhost:8000") as c:
    c.start_protocol("modbus_tcp")
    c.quick_create("modbus_temperature_sensor", "sensor-001")
    points = c.read_points("sensor-001")
    print(points)
    c.create_scenario("factory-001", "factory")
    c.start_scenario("factory-001")
    c.stop_scenario("factory-001")
    c.stop_protocol("modbus_tcp")`,
      csharp: `// ProtoForge C# SDK
using ProtoForge.SDK;

using var client = new ProtoForgeClient("http://localhost:8000");

await client.StartProtocolAsync("modbus_tcp");
await client.QuickCreateAsync("modbus_temperature_sensor", "sensor-001");

var points = await client.ReadPointsAsync("sensor-001");
foreach (var p in points)
    Console.WriteLine($"{p.Name}: {p.Value} {p.Unit}");

await client.CreateScenarioAsync("factory-001", "factory");
await client.StartScenarioAsync("factory-001");
await client.StopScenarioAsync("factory-001");
await client.StopProtocolAsync("modbus_tcp");`,
      java: `// ProtoForge Java SDK
import com.protoforge.sdk.*;

ProtoForgeClient client = new ProtoForgeClient("http://localhost:8000");

client.startProtocol("modbus_tcp");
client.quickCreate("modbus_temperature_sensor", "sensor-001");

List<PointData> points = client.readPoints("sensor-001");
for (PointData p : points) {
    System.out.println(p.getName() + ": " + p.getValue() + " " + p.getUnit());
}

client.createScenario("factory-001", "factory");
client.startScenario("factory-001");
client.stopScenario("factory-001");
client.stopProtocol("modbus_tcp");`,
      go: `// ProtoForge Go SDK
package main

import "github.com/protoforge/sdk-go"

func main() {
    client := protoforge.NewClient("http://localhost:8000")
    
    client.StartProtocol("modbus_tcp")
    client.QuickCreate("modbus_temperature_sensor", "sensor-001")
    
    points, _ := client.ReadPoints("sensor-001")
    for _, p := range points {
        fmt.Printf("%s: %v %s\\n", p.Name, p.Value, p.Unit)
    }
    
    client.CreateScenario("factory-001", "factory")
    client.StartScenario("factory-001")
    client.StopScenario("factory-001")
    client.StopProtocol("modbus_tcp")
}`,
    },
  },
}

export default config
