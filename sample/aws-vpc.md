# AWS VPC Notes

## Subnets and availability zones

A VPC spans a region but each subnet lives in exactly one availability zone.
Public subnets route `0.0.0.0/0` through an Internet Gateway; private
subnets route it through a NAT Gateway sitting in a public subnet instead,
so private instances get outbound internet access without being directly
reachable from it.

## Security groups vs NACLs

Security groups are stateful and attach to individual instances/ENIs - allow
an inbound rule and the matching outbound response is allowed automatically.
Network ACLs are stateless and attach to subnets - both directions need
explicit rules, and they're evaluated in numbered order, first match wins.

## IAM roles for EC2

Instances should get permissions via an instance profile (an IAM role
attached to the instance), never via long-lived access keys baked into the
instance. The instance metadata service hands out short-lived credentials
that the AWS SDK picks up automatically.
