<?php

namespace Emipro\Apichange\Model;

use Emipro\Apichange\Api\AttributeInterface;

/**
 * Defines the implementaiton class of the calculator service contract.
 */
class Attribute implements AttributeInterface
{
	
		
		private $_jsonHelperData;
		

		public function __construct(
			
			\Magento\Framework\Json\Helper\Data $jsonHelperData			
		) {
			$this->_jsonHelperData = $jsonHelperData;
		}
    /**
     * Return the sum of the two numbers.
     *
     * @api
     * @param int $attributeSetId
     * @return array 
     */
    public function attribute($attributeSetId) {
				
					$objectManager = \Magento\Framework\App\ObjectManager::getInstance();
//$setId = $_product->getAttributeSetId(); // Attribute set Id
//$setId = $attributeSetId; // Attribute set Id
        $groups = $objectManager->create('Magento\Eav\Model\Entity\Attribute\Group')
            ->getResourceCollection()
            ->setAttributeSetFilter($attributeSetId)
            //->addFieldToFilter("attribute_group_id",22)
            ->setSortOrder()
            ->load();
		//echo "<pre>";
		//print_r($groups->getData());exit;
        $attributeCodes = array();
        
        foreach ($groups as $group) {
           // if($group->getAttributeGroupName() == 'Somename'){ // set name
            //$groupName          = $group->getAttributeGroupName();
            //$groupId            = $group->getAttributeGroupId();

                $attributes = $objectManager->create('Magento\Catalog\Model\ResourceModel\Product\Attribute\Collection')
                ->setAttributeGroupFilter($group->getId())
                ->addVisibleFilter()
                ->load();
                //->checkConfigurableProducts()
               
$logger=$objectManager->get('\Psr\Log\LoggerInterface');
$logger->critical($attributes->getSelect());


                if ($attributes->getSize() > 0) {
                    foreach ($attributes->getItems() as $attribute) {
                        /* @var $child Mage_Eav_Model_Entity_Attribute */
                       $logger=$objectManager->get('\Psr\Log\LoggerInterface');
$logger->critical($group->getAttributeGroupName());
 
                        $attributeCodes[$group->getAttributeGroupName()][$group->getAttributeGroupName()][$attribute->getAttributeId()][$attribute->getSortOrder()]= $attribute->getAttributeCode();                     
                        //$attributeCodes[]= $attribute->getAttributeCode();   
                                         
                    }
                    $logger->critical(print_r($attributeCodes,true));

                }
              
          
        }
        if(empty($attributeCodes))
		{
			return "No attribute found";
		}
		
		return ($attributeCodes);
      
	}
}
