import boto3
import pandas as pd
import datetime
import io

# AWS Account IDs in your Organization
ACCOUNTS = ["324037307951","652918353734","992382824137","703671910376","246005137240"]
ROLE_NAME = "OrganizationInventoryRole"  # IAM role in each child account
S3_BUCKET = "opl-inventory-details"

# Function to assume role in other accounts
def assume_role(account_id):
    sts_client = boto3.client("sts")
    role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"
    assumed_role = sts_client.assume_role(RoleArn=role_arn, RoleSessionName="InventorySession")
    return boto3.Session(
        aws_access_key_id=assumed_role["Credentials"]["AccessKeyId"],
        aws_secret_access_key=assumed_role["Credentials"]["SecretAccessKey"],
        aws_session_token=assumed_role["Credentials"]["SessionToken"]
    )

# Function to collect EC2 instance type details
def get_instance_types(session):
    ec2_client = session.client("ec2")
    instance_types = {}
    paginator = ec2_client.get_paginator("describe_instance_types")
    for page in paginator.paginate():
        for instance in page["InstanceTypes"]:
            instance_types[instance["InstanceType"]] = {
                "vCPU": instance["VCpuInfo"]["DefaultVCpus"],
                "MemoryGB": instance["MemoryInfo"]["SizeInMiB"] / 1024  # Convert MiB to GB
            }
    return instance_types

# Function to collect inventory data
def collect_inventory(account_id):
    session = assume_role(account_id)
    ec2_client = session.client("ec2")
    rds_client = session.client("rds")
    elb_client = session.client("elbv2")
    s3_client = session.client("s3")
    vpc_client = session.client("ec2")
    
    instance_types = get_instance_types(session)

    inventory_data = {"EC2": [], "RDS": [], "VPC": [], "SecurityGroups": [], "Subnets": [], "LoadBalancers": [], "TargetGroups": [], "S3Buckets": []}
    
    # Fetch EC2 Instances
    for reservation in ec2_client.describe_instances()["Reservations"]:
        for instance in reservation["Instances"]:
            instance_type = instance["InstanceType"]
            vcpu = instance_types.get(instance_type, {}).get("vCPU", "N/A")
            memory_gb = instance_types.get(instance_type, {}).get("MemoryGB", "N/A")
            
            volumes = ec2_client.describe_volumes(Filters=[{"Name": "attachment.instance-id", "Values": [instance["InstanceId"]]}])
            total_volume_size = sum(vol["Size"] for vol in volumes.get("Volumes", []))
            security_groups = ";".join([sg["GroupId"] for sg in instance.get("SecurityGroups", [])])
            inventory_data["EC2"].append({
                "AccountID": account_id, "InstanceId": instance["InstanceId"], "Name": next((tag["Value"] for tag in instance.get("Tags", []) if tag["Key"] == "Name"), "N/A"),
                "State": instance["State"]["Name"], "Type": instance_type, "vCPU": vcpu, "MemoryGB": memory_gb,
                "PublicIP": instance.get("PublicIpAddress", "N/A"), "PrivateIP": instance.get("PrivateIpAddress", "N/A"),
                "AvailabilityZone": instance["Placement"]["AvailabilityZone"], "SecurityGroups": security_groups, "KeyName": instance.get("KeyName", "N/A"), "VPCId": instance.get("VpcId", "N/A"),
                "ImageId": instance["ImageId"], "LaunchTime": str(instance["LaunchTime"]), "SubnetId": instance.get("SubnetId", "N/A"), "Platform": instance.get("Platform", "Linux"),
                "IAMInstanceProfile": instance.get("IamInstanceProfile", {}).get("Arn", "N/A"), "TotalVolumes": len(volumes.get("Volumes", [])), "TotalVolumeSizeGB": total_volume_size
            })
    
#    # Fetch RDS Instances
#    for rds in rds_client.describe_db_instances()["DBInstances"]:
#        inventory_data["RDS"].append({
#            "AccountID": account_id, "DBInstanceIdentifier": rds["DBInstanceIdentifier"], "Engine": rds["Engine"], "Status": rds["DBInstanceStatus"],
#            "DBInstanceClass": rds["DBInstanceClass"], "AvailabilityZone": rds["AvailabilityZone"], "AllocatedStorage": rds["AllocatedStorage"], "VPCId": rds["DBSubnetGroup"]["VpcId"]
#        })
    # Fetch RDS Instances
    for rds in rds_client.describe_db_instances()["DBInstances"]:
        inventory_data["RDS"].append({
            "AccountID": account_id,
            "DBInstanceIdentifier": rds["DBInstanceIdentifier"],
            "Status": rds["DBInstanceStatus"],
            "Engine": rds["Engine"],
            "EngineVersion": rds["EngineVersion"],
            "RDS_Extended_Support": rds.get("SupportsExtendedSupport", "N/A"),
            "Region & AZ": rds["AvailabilityZone"],
            "Size": rds["DBInstanceClass"],
            "Maintenance": rds.get("AutoMinorVersionUpgrade", "N/A"),
            "VPC": rds["DBSubnetGroup"]["VpcId"],
            "Multi-AZ": rds["MultiAZ"],
            "Storage Type": rds["StorageType"],
            "Storage": rds["AllocatedStorage"],
            "Provisioned IOPS": rds.get("Iops", "N/A"),
            "Storage Throughput": rds.get("StorageThroughput", "N/A"),
            "Security Groups": ";".join(sg["VpcSecurityGroupId"] for sg in rds["VpcSecurityGroups"]),
            "DB Subnet Group Name": rds["DBSubnetGroup"]["DBSubnetGroupName"],
            "Option Group": ";".join(og["OptionGroupName"] for og in rds["OptionGroupMemberships"]),
            "Created Time": str(rds["InstanceCreateTime"]),
            "Encrypted": rds["StorageEncrypted"],
            "Parameter Group": ";".join(pg["DBParameterGroupName"] for pg in rds["DBParameterGroups"])
        })

    # Fetch VPCs
    for vpc in vpc_client.describe_vpcs()["Vpcs"]:
        inventory_data["VPC"].append({"AccountID": account_id, "VpcId": vpc["VpcId"], "CIDRBlock": vpc["CidrBlock"], "State": vpc["State"]})
    
    # Fetch Security Groups
    for sg in vpc_client.describe_security_groups()["SecurityGroups"]:
        inventory_data["SecurityGroups"].append({"AccountID": account_id, "GroupId": sg["GroupId"], "GroupName": sg["GroupName"], "Description": sg["Description"], "VPC": sg.get("VpcId", "N/A")})
    
    # Fetch Subnets
    for subnet in vpc_client.describe_subnets()["Subnets"]:
        inventory_data["Subnets"].append({"AccountID": account_id, "SubnetId": subnet["SubnetId"], "VPC": subnet["VpcId"], "CIDRBlock": subnet["CidrBlock"], "AvailabilityZone": subnet["AvailabilityZone"]})
    
    # Fetch Load Balancers
    for lb in elb_client.describe_load_balancers()["LoadBalancers"]:
        inventory_data["LoadBalancers"].append({"AccountID": account_id, "LoadBalancerName": lb["LoadBalancerName"], "DNSName": lb["DNSName"], "State": lb["State"]["Code"], "Type": lb["Type"], "VPC": lb.get("VpcId", "N/A")})
    
    # Fetch Target Groups
    for tg in elb_client.describe_target_groups()["TargetGroups"]:
        inventory_data["TargetGroups"].append({"AccountID": account_id, "TargetGroupName": tg["TargetGroupName"], "Protocol": tg["Protocol"], "Port": tg["Port"], "VPC": tg["VpcId"]})
    
    # Fetch S3 Buckets
    for bucket in s3_client.list_buckets()["Buckets"]:
        inventory_data["S3Buckets"].append({"AccountID": account_id, "BucketName": bucket["Name"]})
    
    return inventory_data

# Save data to Excel
def save_to_excel(data):
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine="xlsxwriter")
    for sheet, records in data.items():
        pd.DataFrame(records).to_excel(writer, sheet_name=sheet, index=False)
    writer.close()
    output.seek(0)
    return output

def upload_to_s3(file_data):
    date_str = datetime.datetime.now().strftime("%d-%m-%Y")
    s3_key = f"{date_str}/aws_inventory_opl_{date_str}.xlsx"
    boto3.client("s3").put_object(Bucket=S3_BUCKET, Key=s3_key, Body=file_data.getvalue())
    print(f"File uploaded to S3: s3://{S3_BUCKET}/{s3_key}")

# Lambda handler
def lambda_handler(event, context):
    all_inventory = {key: [] for key in ["EC2", "RDS", "VPC", "SecurityGroups", "Subnets", "LoadBalancers", "TargetGroups", "S3Buckets"]}
    for account_id in ACCOUNTS:
        for key, records in collect_inventory(account_id).items():
            all_inventory[key].extend(records)
    upload_to_s3(save_to_excel(all_inventory))
    return {"status": "Inventory report generated and uploaded successfully"}
