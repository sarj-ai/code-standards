from types import MappingProxyType


CONTAINER_KINDS = ("containers", "initContainers", "ephemeralContainers")
POD_SPEC_PATHS = MappingProxyType(
    {
        ("v1", "Pod"): ("spec",),
        ("v1", "PodTemplate"): ("template", "spec"),
        ("v1", "ReplicationController"): ("spec", "template", "spec"),
        ("apps/v1", "ReplicaSet"): ("spec", "template", "spec"),
        ("apps/v1", "Deployment"): ("spec", "template", "spec"),
        ("apps/v1", "StatefulSet"): ("spec", "template", "spec"),
        ("apps/v1", "DaemonSet"): ("spec", "template", "spec"),
        ("batch/v1", "Job"): ("spec", "template", "spec"),
        ("batch/v1", "CronJob"): ("spec", "jobTemplate", "spec", "template", "spec"),
    }
)
